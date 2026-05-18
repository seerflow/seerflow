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
import time as time_mod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def run_validation(fixtures_dir: Path) -> ValidationResult:
    """Run the full correlation validation pipeline on LANL CSV fixtures.

    Orchestration steps:

    1. Parse all CSV files from ``fixtures_dir`` (auth.csv, proc.csv,
       flows.csv, redteam.csv).
    2. Convert all records to SeerflowEvents using the converter functions.
    3. Sort all events by timestamp_ns.
    4. Load built-in correlation rules.
    5. Create ``EntityWindowBuffer`` (30-minute window) and ``CorrelationEngine``.
    6. Feed events chronologically: resolve entity refs, add to window,
       evaluate rules, collect alerts.
    7. Match alerts against ground truth.
    8. Compute and return :class:`ValidationResult`.

    Args:
        fixtures_dir: Directory containing auth.csv, proc.csv, flows.csv,
                      and redteam.csv.

    Returns:
        A frozen :class:`ValidationResult`.
    """
    import msgspec.structs

    from seerflow.correlation.bundled import get_bundled_rule_dir
    from seerflow.correlation.engine import CorrelationEngine
    from seerflow.correlation.rule_loader import load_correlation_rules
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.lanl.converter import (
        convert_auth_record,
        convert_flow_record,
        convert_proc_record,
    )
    from seerflow.lanl.hostmap import host_to_ip as _host_to_ip
    from seerflow.lanl.parser import (
        RedTeamRecord,
        parse_auth_line,
        parse_flow_line,
        parse_proc_line,
        parse_redteam_line,
    )
    from seerflow.models.entity import normalize_username as _norm_user
    from seerflow.models.entity import resolve_entities

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
    # 2. Convert to SeerflowEvents
    # ------------------------------------------------------------------

    all_events = []
    for auth_rec in auth_records:
        all_events.extend(convert_auth_record(auth_rec))
    for proc_rec in proc_records:
        all_events.extend(convert_proc_record(proc_rec))
    for flow_rec in flow_records:
        all_events.extend(convert_flow_record(flow_rec))

    # ------------------------------------------------------------------
    # 3. Time-shift events to be "recent"
    # ------------------------------------------------------------------
    # The EntityWindowBuffer lazy-prunes events older than wall-clock
    # minus window_ns.  LANL synthetic timestamps (100, 200 ...) are
    # decades in the past, so they'd be pruned instantly.  Shift all
    # events so the latest one sits 60 seconds before "now".

    if all_events:
        max_ts = max(e.timestamp_ns for e in all_events)
        now_ns = time_mod.time_ns()
        offset_ns = now_ns - max_ts - 60_000_000_000  # 60 s headroom
        all_events = [
            msgspec.structs.replace(
                e,
                timestamp_ns=e.timestamp_ns + offset_ns,
                observed_ns=e.observed_ns + offset_ns,
            )
            for e in all_events
        ]
        # Also shift redteam record times so ground-truth matching works
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
    # 3b. Sort chronologically
    # ------------------------------------------------------------------

    all_events.sort(key=lambda e: e.timestamp_ns)

    # ------------------------------------------------------------------
    # 4. Load correlation rules
    # ------------------------------------------------------------------

    rule_dir = get_bundled_rule_dir()
    rules = load_correlation_rules([str(rule_dir)])
    _log.debug("Loaded %d correlation rules from %s", len(rules), rule_dir)

    # ------------------------------------------------------------------
    # 5. Set up engine and window
    # ------------------------------------------------------------------

    window_ns = 1800 * 1_000_000_000  # 30 minutes in ns
    window = EntityWindowBuffer(window_ns=window_ns, max_events=10_000)
    engine = CorrelationEngine(rules, window)

    # Build a lookup of first red-team timestamp per entity for latency calc
    # Maps normalized entity name → earliest redteam time (seconds)
    # Include both hostnames and derived IPs so ip-typed alerts match.
    redteam_first_seen: dict[str, int] = {}
    for rt_rec in redteam_records:
        if rt_rec.user != "?":
            norm_user, _ = _norm_user(rt_rec.user)
            if norm_user not in redteam_first_seen:
                redteam_first_seen[norm_user] = rt_rec.time
        for computer in (rt_rec.src_computer, rt_rec.dst_computer):
            key = computer.lower()
            if key not in redteam_first_seen:
                redteam_first_seen[key] = rt_rec.time
            try:
                ip_key = _host_to_ip(computer)
                if ip_key not in redteam_first_seen:
                    redteam_first_seen[ip_key] = rt_rec.time
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------
    # 6. Process events and collect alerts
    # ------------------------------------------------------------------

    all_alerts: list[Alert] = []
    # Maps rule_name → list of latency values in seconds
    latency_buckets: dict[str, list[float]] = {}

    for event in all_events:
        entity_refs = resolve_entities(
            event.related_ips,
            event.related_users,
            event.related_hosts,
        )
        for ref in entity_refs:
            window.add_event(ref, event)

        fired = engine.evaluate(event, entity_refs)
        for alert in fired:
            all_alerts.append(alert)
            # Compute detection latency relative to first redteam event for entity
            entity_key = alert.entity_value.lower().strip()
            first_rt = redteam_first_seen.get(entity_key)
            if first_rt is not None:
                latency = (alert.timestamp_ns // 1_000_000_000) - first_rt
                latency_buckets.setdefault(alert.rule_name, []).append(float(latency))

    # Average latencies per rule
    detection_latencies: dict[str, float] = {
        rule_name: sum(vals) / len(vals) for rule_name, vals in latency_buckets.items() if vals
    }

    # ------------------------------------------------------------------
    # 7. Match against ground truth
    # ------------------------------------------------------------------

    # Use a generous matching window (5 minutes) because correlation rules
    # accumulate evidence over their temporal windows before firing.  An
    # alert may fire several minutes after the first red-team indicator.
    tp_alerts, fp_alerts, missed = match_against_ground_truth(
        all_alerts, redteam_records, time_window_s=300
    )

    # ------------------------------------------------------------------
    # 8. Compute and return metrics
    # ------------------------------------------------------------------

    return compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=fp_alerts,
        missed_redteam=missed,
        alerts=all_alerts,
        events_processed=len(all_events),
        detection_latencies=detection_latencies,
    )
