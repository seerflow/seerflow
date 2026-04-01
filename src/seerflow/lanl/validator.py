"""LANL validation harness: computes detection metrics against red-team ground truth.

Matches correlation alerts produced by the Seerflow engine against the LANL
red-team label file to compute precision, recall, and detection latency.

The main entry point is :func:`run_validation`, which orchestrates the full
pipeline end-to-end from raw LANL CSV files to a :class:`ValidationResult`.
"""

from __future__ import annotations

import contextlib
import logging
import time as time_mod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from seerflow.lanl.parser import RedTeamRecord
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of running correlation validation against ground truth."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float  # TP / (TP + FP), 0.0 if no alerts
    recall: float  # TP / (TP + FN), 0.0 if no red-team events
    detection_latency_s: dict[str, float]  # rule_name → avg latency in seconds
    patterns_detected: frozenset[str]  # distinct rule names that fired on red-team activity
    total_events_processed: int
    total_alerts: int


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

    patterns_detected = frozenset(a.rule_name for a in tp_alerts)

    return ValidationResult(
        true_positives=n_tp,
        false_positives=n_fp,
        false_negatives=n_fn,
        precision=precision,
        recall=recall,
        detection_latency_s=detection_latencies,
        patterns_detected=patterns_detected,
        total_events_processed=events_processed,
        total_alerts=len(alerts),
    )


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
    from seerflow.correlation.bundled import get_bundled_rule_dir
    from seerflow.correlation.engine import CorrelationEngine
    from seerflow.correlation.rule_loader import load_correlation_rules
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.lanl.converter import (
        convert_auth_record,
        convert_flow_record,
        convert_proc_record,
    )
    from seerflow.lanl.parser import (
        parse_auth_line,
        parse_flow_line,
        parse_proc_line,
        parse_redteam_line,
    )
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

    import msgspec.structs

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
        from seerflow.lanl.parser import RedTeamRecord

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

    window_ns = int(1800 * 1e9)  # 30 minutes
    window = EntityWindowBuffer(window_ns=window_ns, max_events=10_000)
    engine = CorrelationEngine(rules, window)

    # Build a lookup of first red-team timestamp per entity for latency calc
    # Maps normalized entity name → earliest redteam time (seconds)
    # Include both hostnames and derived IPs so ip-typed alerts match.
    from seerflow.lanl.hostmap import host_to_ip as _host_to_ip
    from seerflow.models.entity import normalize_username as _norm_user

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
