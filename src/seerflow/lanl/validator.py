"""LANL validation harness: computes detection metrics against red-team ground truth.

Routes time-rebased :class:`~seerflow.receivers.base.RawEvent`\\ s through the
**full detection stack** (Drain3 → ML ensemble → Sigma → UEBA → IoC →
correlation) via :func:`seerflow.pipeline.assembly.assemble_handler` — the
identical wiring as live ``seerflow start`` — then scores the persisted alerts
against the LANL red-team label file (precision/recall/F1 per detector family
and combined). The scope is the committed synthetic LANL subset unless
``run_validation`` is pointed at a downloaded full-dataset directory; it does
**not** by itself constitute "end-to-end on the full LANL dataset".

The synchronous entry point is :func:`run_validation`; it wraps the async
driver :func:`run_validation_async` in ``asyncio.run``.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from seerflow.lanl.parser import AuthRecord, FlowRecord, ProcRecord, RedTeamRecord
    from seerflow.models.alert import Alert
    from seerflow.receivers.base import RawEvent

_log = logging.getLogger("seerflow")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


DEFAULT_SCOPE_LABEL = (
    "full detection stack (Drain3+ML+Sigma+UEBA+IoC+correlation) on "
    "synthetic LANL subset (~200 events, tests/fixtures/lanl)"
)


@dataclass(frozen=True, slots=True)
class FamilyMetrics:
    """Per-detector-family detection sub-metrics.

    ``false_negatives`` is always 0 here: a missed red-team event fired no
    alert at all, so the miss cannot be attributed to any single detector
    family. The meaningful recall is the *combined* one on
    :class:`ValidationResult`; per-family ``recall`` is 1.0 when the family
    produced ≥1 true positive (every alert it fired was correct) else 0.0.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    total_alerts: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of running full-stack detection validation against ground truth."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float  # TP / (TP + FP), 0.0 if no alerts
    recall: float  # TP / (TP + FN), 0.0 if no red-team events
    f1_score: float  # 2PR / (P + R), 0.0 if P + R == 0
    false_positive_rate: float  # FP / (FP + TP), 0.0 if no alerts
    detection_latency_s: dict[str, float]  # rule_name → avg latency in seconds
    patterns_detected: frozenset[str]  # distinct rule names that fired on red-team activity
    total_events_processed: int
    total_alerts: int
    per_family: dict[str, FamilyMetrics] = field(default_factory=dict)
    scope_label: str = DEFAULT_SCOPE_LABEL


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------


def match_against_ground_truth(
    alerts: list[Alert],
    redteam_records: list[RedTeamRecord],
    time_window_s: int = 60,
) -> tuple[list[Alert], list[Alert], list[RedTeamRecord]]:
    """Match correlation alerts against red-team ground truth records.

    An alert is a **true positive** if there exists a RedTeamRecord where:
    - The alert's ``entity_value`` (lowercased) overlaps with the redteam
      record's normalized user OR ``src_computer`` OR ``dst_computer``.
    - The absolute time difference between alert and redteam event is within
      ``time_window_s`` seconds.

    An alert that matches no redteam record is a **false positive**.
    A redteam record that no alert matched is a **false negative** (missed).

    Args:
        alerts: Alerts produced by the correlation engine.
        redteam_records: Ground-truth red-team records.
        time_window_s: Maximum allowed time difference in seconds.

    Returns:
        Tuple of ``(true_positive_alerts, false_positive_alerts, missed_redteam_records)``.
    """
    from seerflow.lanl.hostmap import host_to_ip
    from seerflow.models.entity import normalize_username

    matched_redteam_indices: set[int] = set()
    tp_alerts: list[Alert] = []
    fp_alerts: list[Alert] = []

    for alert in alerts:
        alert_time_s = alert.timestamp_ns // 1_000_000_000
        alert_entity = alert.entity_value.lower().strip()

        matched = False
        for idx, rec in enumerate(redteam_records):
            if abs(alert_time_s - rec.time) > time_window_s:
                continue

            # Normalize redteam user for comparison
            if rec.user != "?":
                norm_user, _domain = normalize_username(rec.user)
            else:
                norm_user = ""

            # Build candidate set: user, hostnames, and derived IPs.
            # IP-typed alerts have entity_value = derived IP (e.g. "10.0.69.29"),
            # while redteam records have hostnames (e.g. "C17693").
            # Each host_to_ip call is wrapped independently so a failure on
            # one hostname doesn't prevent the other from being added.
            candidates = {norm_user, rec.src_computer.lower(), rec.dst_computer.lower()}
            for host_field in (rec.src_computer, rec.dst_computer):
                with contextlib.suppress(ValueError, TypeError):
                    candidates.add(host_to_ip(host_field))

            if alert_entity in candidates:
                matched = True
                matched_redteam_indices.add(idx)
                # Do not break — one alert can confirm multiple redteam events

        if matched:
            tp_alerts.append(alert)
        else:
            fp_alerts.append(alert)

    missed_redteam = [
        rec for idx, rec in enumerate(redteam_records) if idx not in matched_redteam_indices
    ]

    return tp_alerts, fp_alerts, missed_redteam


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def compute_metrics(
    *,
    tp_alerts: list[Alert],
    fp_alerts: list[Alert],
    missed_redteam: list[RedTeamRecord],
    alerts: list[Alert],
    events_processed: int,
    detection_latencies: dict[str, float],
) -> ValidationResult:
    """Compute precision, recall, and metadata from matched results.

    Args:
        tp_alerts: True-positive alert list.
        fp_alerts: False-positive alert list.
        missed_redteam: Unmatched red-team records (false negatives).
        alerts: All alerts (tp + fp combined).
        events_processed: Total number of SeerflowEvents fed to the engine.
        detection_latencies: Mapping of rule_name → average latency in seconds.

    Returns:
        A frozen :class:`ValidationResult`.
    """
    n_tp = len(tp_alerts)
    n_fp = len(fp_alerts)
    n_fn = len(missed_redteam)

    precision = n_tp / (n_tp + n_fp) if (n_tp + n_fp) > 0 else 0.0
    recall = n_tp / (n_tp + n_fn) if (n_tp + n_fn) > 0 else 0.0
    f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    false_positive_rate = n_fp / (n_fp + n_tp) if (n_fp + n_tp) > 0 else 0.0

    patterns_detected = frozenset(a.rule_name for a in tp_alerts)

    # Per-detector-family breakdown (FR-073 AC4). Families with no alerts at
    # all are skipped so the dict only carries detectors that actually fired.
    families = ("ml", "sigma", "correlation", "ueba", "ioc")
    per_family: dict[str, FamilyMetrics] = {}
    for fam in families:
        fam_tp = [a for a in tp_alerts if a.alert_type == fam]
        fam_fp = [a for a in fp_alerts if a.alert_type == fam]
        n_ftp = len(fam_tp)
        n_ffp = len(fam_fp)
        if n_ftp == 0 and n_ffp == 0:
            continue
        f_precision = n_ftp / (n_ftp + n_ffp) if (n_ftp + n_ffp) > 0 else 0.0
        f_recall = 1.0 if n_ftp > 0 else 0.0
        f_f1 = (
            2 * f_precision * f_recall / (f_precision + f_recall)
            if (f_precision + f_recall) > 0
            else 0.0
        )
        per_family[fam] = FamilyMetrics(
            true_positives=n_ftp,
            false_positives=n_ffp,
            false_negatives=0,
            precision=f_precision,
            recall=f_recall,
            f1_score=f_f1,
            total_alerts=n_ftp + n_ffp,
        )

    return ValidationResult(
        true_positives=n_tp,
        false_positives=n_fp,
        false_negatives=n_fn,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        false_positive_rate=false_positive_rate,
        detection_latency_s=detection_latencies,
        patterns_detected=patterns_detected,
        total_events_processed=events_processed,
        total_alerts=len(alerts),
        per_family=per_family,
    )


# ---------------------------------------------------------------------------
# RawEvent construction (functional review §A.5 / §A.9)
# ---------------------------------------------------------------------------


def _build_raw_events(
    auth_records: list[AuthRecord],
    proc_records: list[ProcRecord],
    flow_records: list[FlowRecord],
) -> list[RawEvent]:
    """Build one textual ``RawEvent`` per LANL record.

    Emits raw text bytes (the message strings the legacy converter crafted to
    match the brute-force / credential-stuffing / C2 regexes) so the
    in-handler ``EventNormalizer`` runs Drain3 + entity extraction exactly as
    a live receiver would (functional review §A.5/§A.9). One record → one
    ``RawEvent``; ``related_*`` are re-derived from the text by the real
    ``EntityExtractor`` (no pre-split user/ip views).

    Timestamps are raw record seconds → ns; chronological rebasing against
    wall-clock is the async driver's job (keeps this function pure).
    """
    from seerflow.lanl.hostmap import host_to_ip
    from seerflow.models.entity import normalize_username
    from seerflow.receivers.base import RawEvent

    events: list[RawEvent] = []

    for rec in auth_records:
        dst_user, _domain = normalize_username(rec.dst_user)
        if rec.success:
            msg = f"Accepted password for {dst_user} session opened from {rec.src_computer}"
        else:
            msg = (
                f"authentication failure for {dst_user} from {rec.src_computer} "
                f"via {rec.auth_type}"
            )
        events.append(
            RawEvent(
                data=msg.encode("utf-8"),
                source_type="syslog",
                source_id="lanl-auth",
                received_ns=rec.time * 1_000_000_000,
                metadata={},
            )
        )

    for prec in proc_records:
        username, _domain = normalize_username(prec.user)
        action = "start" if prec.start_end.lower() == "start" else "end"
        msg = f"process {action}: {prec.process_name} by {username} on {prec.computer}"
        events.append(
            RawEvent(
                data=msg.encode("utf-8"),
                source_type="syslog",
                source_id="lanl-proc",
                received_ns=prec.time * 1_000_000_000,
                metadata={},
            )
        )

    for frec in flow_records:
        src_ip = host_to_ip(frec.src_computer)
        dst_ip = host_to_ip(frec.dst_computer)
        msg = (
            f"flow established {dst_ip}:{frec.dst_port} from "
            f"{src_ip}:{frec.src_port} {frec.byte_count}B"
        )
        events.append(
            RawEvent(
                data=msg.encode("utf-8"),
                source_type="syslog",
                source_id="lanl-flow",
                received_ns=frec.time * 1_000_000_000,
                metadata={},
            )
        )

    return events


def _rebased(raw: RawEvent, offset_ns: int) -> RawEvent:
    """Return a copy of ``raw`` with ``received_ns`` shifted by ``offset_ns``.

    ``RawEvent`` is a frozen ``dataclass`` (not a msgspec Struct), so this
    uses :func:`dataclasses.replace`.
    """
    import dataclasses

    return dataclasses.replace(raw, received_ns=raw.received_ns + offset_ns)


# Deterministic replay epoch. The harness rebases every LANL record so the
# latest event sits exactly REPLAY_HEADROOM_NS before this fixed anchor; the
# anchor is a constant (not ``time.time_ns()``) so the rebase offset — and
# therefore every downstream timestamp — is identical on every machine.
#
# 2026-01-01T00:00:00Z in nanoseconds (arbitrary fixed point comfortably
# inside the storage/correlation working range; the absolute value is
# irrelevant, only its constancy matters).
REPLAY_EPOCH_NS = 1_767_225_600_000_000_000
REPLAY_HEADROOM_NS = 60_000_000_000  # 60 s between newest event and "now"


@contextlib.contextmanager
def _frozen_replay_clock(now_ns: int) -> Iterator[None]:
    """Freeze ``time.time_ns()`` for the wall-clock-relative aging components.

    Two components inside the full detection stack measure *event age*
    against ``time.time_ns()`` rather than against the event stream:

    * :class:`seerflow.correlation.window.EntityWindowBuffer` lazily prunes
      events older than ``now - window_ns`` on every query.
    * :class:`seerflow.correlation.risk.RiskRegister` applies exponential
      decay using ``now - entry.timestamp_ns``.

    In live operation ``now`` is real wall-clock and these are correct. But
    the harness *replays* historical events as fast as the machine allows,
    so a slower runner lets more real time elapse during the replay and the
    aging boundary drifts relative to the (fixed) rebased event timestamps —
    making the headline metric environment-nondeterministic (the CI failure:
    P=16.67% locally vs 18.18% in CI).

    Pinning the clock these two modules observe to a constant ``now_ns`` for
    the duration of the replay makes window pruning and risk decay a pure
    function of the (deterministic) event timestamps, so the metrics are
    byte-identical on every machine. Production wiring is untouched: this
    only patches the modules' ``time.time_ns`` within this ``with`` block and
    restores the originals on exit (including on exception).
    """
    import time as _time
    from typing import Any, cast

    from seerflow.correlation import risk as _risk_mod
    from seerflow.correlation import window as _window_mod

    class _FrozenClock:
        """Drop-in stand-in for the ``time`` module exposing a fixed
        ``time_ns()``; every other ``time`` attribute proxies to the real
        module so nothing else in the correlation modules breaks."""

        def time_ns(self) -> int:
            return now_ns

        def __getattr__(self, name: str) -> Any:
            return getattr(_time, name)

    frozen = _FrozenClock()
    # window.py / risk.py both do ``import time``; rebind that name in
    # their module namespace to the frozen stand-in for the replay only,
    # leaving the real stdlib ``time`` module untouched (surgical: no
    # global side effects, restored in ``finally``). ``setattr`` on the
    # cast-to-Any module objects keeps mypy happy about patching a name
    # that the correlation modules don't re-export.
    win: Any = cast("Any", _window_mod)
    rsk: Any = cast("Any", _risk_mod)
    saved_window = win.time
    saved_risk = rsk.time
    win.time = frozen
    rsk.time = frozen
    try:
        yield
    finally:
        win.time = saved_window
        rsk.time = saved_risk


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


async def run_validation_async(fixtures_dir: Path) -> ValidationResult:
    """Full-stack LANL validation via the S-302 ``assemble_handler`` seam.

    Routes time-rebased :class:`~seerflow.receivers.base.RawEvent`\\ s through
    the identical detection wiring as live ``seerflow start`` (Drain3 → ML →
    Sigma → UEBA → IoC → correlation), reads the persisted alerts back from
    SQLite, and scores them against the red-team ground truth — per detector
    family and combined (FR-073).

    Orchestration:

    1. Parse the four LANL CSV files from ``fixtures_dir``.
    2. Build one textual ``RawEvent`` per record (Drain3 + entity extraction
       run inside the handler — functional review §A.5/§A.9).
    3. Time-rebase so the latest event sits 60 s before wall-clock ``now``
       (the ``EntityWindowBuffer`` lazy-prunes; LANL synthetic timestamps are
       decades old). Apply the same offset to ``RedTeamRecord.time``.
    4. ``connect_storage`` (temp SQLite) → ``assemble_handler`` → feed every
       ``RawEvent`` chronologically → ``teardown`` → ``query_alerts``.
    5. Match alerts vs ground truth and compute per-family + combined metrics.

    Args:
        fixtures_dir: Directory containing auth.csv, proc.csv, flows.csv,
                      and redteam.csv.

    Returns:
        A frozen :class:`ValidationResult`.
    """
    import tempfile

    from seerflow.config import SeerflowConfig, StorageConfig
    from seerflow.lanl.parser import (
        RedTeamRecord,
        parse_auth_line,
        parse_flow_line,
        parse_proc_line,
        parse_redteam_line,
    )
    from seerflow.models.query import AlertQuery
    from seerflow.pipeline.assembly import assemble_handler
    from seerflow.storage import connect_storage

    # ------------------------------------------------------------------
    # 1. Parse CSV files
    # ------------------------------------------------------------------

    def _read_lines(filename: str) -> list[str]:
        p = fixtures_dir / filename
        if not p.exists():
            return []
        return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    auth_records = [parse_auth_line(ln) for ln in _read_lines("auth.csv")]
    proc_records = [parse_proc_line(ln) for ln in _read_lines("proc.csv")]
    flow_records = [parse_flow_line(ln) for ln in _read_lines("flows.csv")]
    redteam_records = [parse_redteam_line(ln) for ln in _read_lines("redteam.csv")]

    # ------------------------------------------------------------------
    # 2. Build textual RawEvents (one per record) — §A.5/§A.9
    # ------------------------------------------------------------------

    raw_events = _build_raw_events(auth_records, proc_records, flow_records)

    if not raw_events:
        return compute_metrics(
            tp_alerts=[],
            fp_alerts=[],
            missed_redteam=redteam_records,
            alerts=[],
            events_processed=0,
            detection_latencies={},
        )

    # ------------------------------------------------------------------
    # 3. Time-rebase against a FIXED deterministic epoch
    # ------------------------------------------------------------------
    #
    # The newest event is pinned exactly REPLAY_HEADROOM_NS before the
    # constant REPLAY_EPOCH_NS (not before live ``time.time_ns()``), so the
    # rebase offset — and every downstream timestamp — is identical on every
    # machine. The replay clock is then frozen to this same epoch (step 4)
    # so the wall-clock-relative aging components stay deterministic.

    max_ts = max(r.received_ns for r in raw_events)
    offset_ns = REPLAY_EPOCH_NS - max_ts - REPLAY_HEADROOM_NS
    raw_events = sorted(
        (_rebased(r, offset_ns) for r in raw_events),
        key=lambda r: r.received_ns,
    )
    offset_s = offset_ns // 1_000_000_000
    redteam_records = [
        RedTeamRecord(
            time=rt.time + offset_s,
            user=rt.user,
            src_computer=rt.src_computer,
            dst_computer=rt.dst_computer,
        )
        for rt in redteam_records
    ]

    # ------------------------------------------------------------------
    # 4. Drive the full detection stack via assemble_handler
    # ------------------------------------------------------------------

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_cfg = StorageConfig(backend="sqlite", sqlite_path=f"{tmpdir}/lanl.db")
        storage = await connect_storage(storage_cfg)
        try:
            config = SeerflowConfig()
            # capture_sink=None: the harness reads alerts back from the
            # AlertStore (the same persistence `seerflow analyze --persist`
            # produces); the assemble_handler capture_sink seam is S-303's.
            assembled = await assemble_handler(config, storage)
            try:
                # Freeze the clock the window-buffer / risk-register observe
                # to the same epoch the events were rebased against, so
                # pruning + decay are a pure function of the deterministic
                # event timestamps (machine-speed independent).
                with _frozen_replay_clock(REPLAY_EPOCH_NS):
                    for raw in raw_events:
                        await assembled.handler(raw)
            finally:
                await assembled.teardown()
            await storage.flush()
            page = await storage.query_alerts(AlertQuery(limit=10_000))
            all_alerts: list[Alert] = list(page.items)
        finally:
            await storage.close()

    # ------------------------------------------------------------------
    # 5. Match against ground truth + compute metrics
    # ------------------------------------------------------------------

    # Generous 5-minute matching window: detectors accumulate evidence over
    # their temporal windows before firing, so an alert may land minutes
    # after the first red-team indicator.
    tp_alerts, fp_alerts, missed = match_against_ground_truth(
        all_alerts, redteam_records, time_window_s=300
    )

    return compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=fp_alerts,
        missed_redteam=missed,
        alerts=all_alerts,
        events_processed=len(raw_events),
        detection_latencies={},
    )


def run_validation(fixtures_dir: Path) -> ValidationResult:
    """Synchronous entry point — wraps the async full-stack driver.

    The public signature is unchanged so existing callers (tests,
    ``report._main``) keep working. Internally delegates to
    :func:`run_validation_async` via ``asyncio.run`` (functional review §A.7 —
    the agreed pattern for the now-async harness). For callers already inside
    an event loop, await :func:`run_validation_async` directly.
    """
    import asyncio

    return asyncio.run(run_validation_async(fixtures_dir))
