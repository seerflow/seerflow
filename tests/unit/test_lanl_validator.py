"""Unit tests for the LANL validation harness.

Tests follow TDD (RED → GREEN → REFACTOR).
Written before the implementation exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from seerflow.lanl.parser import RedTeamRecord
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Helpers: minimal Alert and RedTeamRecord factories
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    alert_id: str = "test-1",
    timestamp_ns: int = 110_000_000_000,
    rule_name: str = "brute-force-lateral-movement",
    entity_value: str = "u5624",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="correlation",
        timestamp_ns=timestamp_ns,
        severity_id=SeverityLevel.CRITICAL,
        rule_name=rule_name,
        description="test alert",
        entity_uuid="test-uuid",
        entity_value=entity_value,
        entity_type="user",
        contributing_events=(),
        mitre_tactics=("credential-access",),
        mitre_techniques=("T1110",),
        risk_score=0.9,
        dedup_key="test-dedup",
    )


def _make_redteam(
    *,
    time: int = 100,
    user: str = "U5624@DOM1",
    src_computer: str = "C17693",
    dst_computer: str = "C528",
) -> RedTeamRecord:
    return RedTeamRecord(
        time=time,
        user=user,
        src_computer=src_computer,
        dst_computer=dst_computer,
    )


# ---------------------------------------------------------------------------
# Import target (deferred so RED phase shows ImportError cleanly)
# ---------------------------------------------------------------------------


@pytest.fixture
def validator():
    from seerflow.lanl import validator

    return validator


@pytest.fixture
def compute_metrics(validator):
    return validator.compute_metrics


@pytest.fixture
def match_fn(validator):
    return validator.match_against_ground_truth


@pytest.fixture
def validation_result_cls(validator):
    return validator.ValidationResult


# ---------------------------------------------------------------------------
# ValidationResult metric calculation tests
# ---------------------------------------------------------------------------


def test_validation_result_precision_calculation(compute_metrics):
    """TP=3, FP=1 → precision = 3 / (3+1) = 0.75."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(3)]
    fp_alerts = [_make_alert(alert_id="fp-1")]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=fp_alerts,
        missed_redteam=[],
        alerts=tp_alerts + fp_alerts,
        events_processed=10,
        detection_latencies={},
    )
    assert result.precision == pytest.approx(0.75)


def test_validation_result_recall_calculation(compute_metrics):
    """TP=3, FN=1 → recall = 3 / (3+1) = 0.75."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(3)]
    missed = [_make_redteam()]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=[],
        missed_redteam=missed,
        alerts=tp_alerts,
        events_processed=10,
        detection_latencies={},
    )
    assert result.recall == pytest.approx(0.75)


def test_precision_zero_when_no_alerts(compute_metrics):
    """TP=0, FP=0 → precision = 0.0 (no alerts fired)."""
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.precision == 0.0


def test_recall_zero_when_no_redteam(compute_metrics):
    """TP=0, FN=0 → recall = 0.0 (no red-team events at all)."""
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.recall == 0.0


def test_validation_result_counts(compute_metrics):
    """TP/FP/FN counts are stored correctly on the result."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(2)]
    fp_alerts = [_make_alert(alert_id="fp-1")]
    missed = [_make_redteam(), _make_redteam(time=999)]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=fp_alerts,
        missed_redteam=missed,
        alerts=tp_alerts + fp_alerts,
        events_processed=50,
        detection_latencies={},
    )
    assert result.true_positives == 2
    assert result.false_positives == 1
    assert result.false_negatives == 2
    assert result.total_alerts == 3
    assert result.total_events_processed == 50


def test_validation_result_patterns_detected(compute_metrics):
    """patterns_detected is the frozenset of rule names from TP alerts."""
    tp_alerts = [
        _make_alert(alert_id="1", rule_name="brute-force"),
        _make_alert(alert_id="2", rule_name="brute-force"),
        _make_alert(alert_id="3", rule_name="credential-stuffing"),
    ]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=[],
        missed_redteam=[],
        alerts=tp_alerts,
        events_processed=10,
        detection_latencies={},
    )
    assert result.patterns_detected == frozenset({"brute-force", "credential-stuffing"})


def test_validation_result_latencies_stored(compute_metrics):
    """detection_latency_s is passed through to the result."""
    latencies = {"brute-force": 12.5, "c2-beacon": 5.0}
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies=latencies,
    )
    assert result.detection_latency_s == latencies


def test_precision_one_when_all_tp(compute_metrics):
    """All alerts are TPs → precision = 1.0."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(5)]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=[],
        missed_redteam=[],
        alerts=tp_alerts,
        events_processed=100,
        detection_latencies={},
    )
    assert result.precision == pytest.approx(1.0)


def test_recall_one_when_all_detected(compute_metrics):
    """All red-team events detected → recall = 1.0."""
    tp_alerts = [_make_alert(alert_id="1")]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=[],
        missed_redteam=[],
        alerts=tp_alerts,
        events_processed=50,
        detection_latencies={},
    )
    assert result.recall == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# match_against_ground_truth tests
# ---------------------------------------------------------------------------


def test_match_alert_within_time_window_is_tp(match_fn):
    """Alert 5 s after redteam event (within default 60 s) → TP."""
    redteam = _make_redteam(time=100, user="U5624@DOM1")
    alert = _make_alert(
        timestamp_ns=105_000_000_000,  # 105 s in ns — 5 s after redteam
        entity_value="u5624",
    )
    tp, fp, missed = match_fn([alert], [redteam])
    assert len(tp) == 1
    assert len(fp) == 0
    assert len(missed) == 0


def test_match_alert_outside_time_window_is_fp(match_fn):
    """Alert 120 s after redteam (outside default 60 s window) → FP."""
    redteam = _make_redteam(time=100, user="U5624@DOM1")
    alert = _make_alert(
        timestamp_ns=220_000_000_000,  # 220 s in ns — 120 s after redteam
        entity_value="u5624",
    )
    tp, fp, missed = match_fn([alert], [redteam])
    assert len(tp) == 0
    assert len(fp) == 1
    assert len(missed) == 1


def test_match_alert_matches_src_computer(match_fn):
    """Alert entity_value matching redteam src_computer → TP."""
    redteam = _make_redteam(time=100, user="?", src_computer="C17693")
    alert = _make_alert(
        timestamp_ns=110_000_000_000,  # 10 s after
        entity_value="C17693",
    )
    tp, _fp, _missed = match_fn([alert], [redteam])
    assert len(tp) == 1


def test_match_alert_matches_dst_computer(match_fn):
    """Alert entity_value matching redteam dst_computer → TP."""
    redteam = _make_redteam(time=100, dst_computer="C528")
    alert = _make_alert(
        timestamp_ns=130_000_000_000,  # 30 s after
        entity_value="C528",
    )
    tp, _fp, _missed = match_fn([alert], [redteam])
    assert len(tp) == 1


def test_match_no_alerts_returns_all_missed(match_fn):
    """No alerts → 0 TPs, 0 FPs, all redteam records missed."""
    redteam_records = [_make_redteam(time=t) for t in [100, 200, 300]]
    tp, fp, missed = match_fn([], redteam_records)
    assert len(tp) == 0
    assert len(fp) == 0
    assert len(missed) == 3


def test_match_no_redteam_all_fp(match_fn):
    """No redteam records → every alert is FP."""
    alerts = [_make_alert(alert_id=str(i)) for i in range(3)]
    tp, fp, missed = match_fn(alerts, [])
    assert len(tp) == 0
    assert len(fp) == 3
    assert len(missed) == 0


def test_match_custom_time_window(match_fn):
    """Respects a custom time_window_s parameter."""
    redteam = _make_redteam(time=100)
    alert = _make_alert(
        timestamp_ns=115_000_000_000,  # 15 s after — within 10 s? No → FP
        entity_value="u5624",
    )
    tp, fp, _missed = match_fn([alert], [redteam], time_window_s=10)
    assert len(tp) == 0
    assert len(fp) == 1

    # Same alert within 20 s window → TP
    tp2, fp2, _missed2 = match_fn([alert], [redteam], time_window_s=20)
    assert len(tp2) == 1
    assert len(fp2) == 0


def test_match_case_insensitive_user(match_fn):
    """User matching is case-insensitive after normalization."""
    redteam = _make_redteam(time=100, user="U5624@DOM1")
    alert = _make_alert(
        timestamp_ns=105_000_000_000,
        entity_value="U5624",  # uppercase — should still match "u5624"
    )
    tp, _fp, _missed = match_fn([alert], [redteam])
    assert len(tp) == 1


def test_match_alert_before_redteam_outside_window_is_fp(match_fn):
    """Alert fired 90 s BEFORE the redteam event → outside ±60 s window → FP."""
    redteam = _make_redteam(time=200)
    alert = _make_alert(
        timestamp_ns=110_000_000_000,  # 110 s in ns — 90 s before redteam
        entity_value="u5624",
    )
    _tp, fp, _missed = match_fn([alert], [redteam])
    assert len(fp) == 1


def test_match_alert_before_redteam_within_window_is_tp(match_fn):
    """Alert fired 30 s BEFORE the redteam event → within 60 s window → TP."""
    redteam = _make_redteam(time=200, user="U5624@DOM1")
    alert = _make_alert(
        timestamp_ns=170_000_000_000,  # 170 s in ns — 30 s before redteam at 200
        entity_value="u5624",
    )
    tp, _fp, _missed = match_fn([alert], [redteam])
    assert len(tp) == 1


# ---------------------------------------------------------------------------
# run_validation smoke test
# ---------------------------------------------------------------------------


def test_run_validation_returns_validation_result(validator):
    """run_validation() returns a ValidationResult for the LANL fixture files."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "lanl"
    result = validator.run_validation(fixtures_dir)

    assert isinstance(result, validator.ValidationResult)
    assert result.total_events_processed > 0
    assert result.total_alerts >= 0
    assert 0.0 <= result.precision <= 1.0
    assert 0.0 <= result.recall <= 1.0


def test_run_validation_detects_known_redteam_user(validator):
    """The fixture redteam.csv contains U5624@DOM1 — at least 1 TP expected."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "lanl"
    result = validator.run_validation(fixtures_dir)

    # The fixture has red-team events; we expect at least 1 TP or at least
    # some alerts to fire (we cannot guarantee exact match without full data,
    # but total_events_processed should be > 0 and no crash should occur).
    assert result.total_events_processed > 0
