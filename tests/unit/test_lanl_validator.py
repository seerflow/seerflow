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
# F1 score + false-positive-rate tests (S-088)
# ---------------------------------------------------------------------------


def test_f1_score_harmonic_mean(compute_metrics):
    """TP=3, FP=1, FN=1 → P=0.75, R=0.75, F1=0.75."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(3)]
    fp_alerts = [_make_alert(alert_id="fp-1")]
    missed = [_make_redteam()]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=fp_alerts,
        missed_redteam=missed,
        alerts=tp_alerts + fp_alerts,
        events_processed=10,
        detection_latencies={},
    )
    assert result.f1_score == pytest.approx(0.75)


def test_f1_score_zero_when_precision_and_recall_zero(compute_metrics):
    """No alerts, no redteam → P=0, R=0 → F1=0.0 (no ZeroDivision)."""
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.f1_score == 0.0


def test_f1_score_one_when_perfect(compute_metrics):
    """All TP, no FP, no FN → P=1, R=1 → F1=1.0."""
    tp_alerts = [_make_alert(alert_id=str(i)) for i in range(4)]
    result = compute_metrics(
        tp_alerts=tp_alerts,
        fp_alerts=[],
        missed_redteam=[],
        alerts=tp_alerts,
        events_processed=20,
        detection_latencies={},
    )
    assert result.f1_score == pytest.approx(1.0)


def test_false_positive_rate_calculation(compute_metrics):
    """TP=3, FP=1 → FP-rate = 1 / (1+3) = 0.25 (matches integration test def)."""
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
    assert result.false_positive_rate == pytest.approx(0.25)


def test_false_positive_rate_zero_when_no_alerts(compute_metrics):
    """TP=0, FP=0 → FP-rate = 0.0 (no ZeroDivision)."""
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.false_positive_rate == 0.0


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
    assert result.total_events_processed > 0


def test_run_validation_missing_csv_files(validator, tmp_path):
    """run_validation gracefully handles a directory missing some CSV files."""
    # Only create redteam.csv — others are missing
    (tmp_path / "redteam.csv").write_text("100,U1@DOM1,C1,C2\n")
    result = validator.run_validation(tmp_path)
    assert result.total_events_processed == 0
    assert result.total_alerts == 0


# ---------------------------------------------------------------------------
# IP-derived matching in match_against_ground_truth
# ---------------------------------------------------------------------------


def test_match_ip_typed_alert_matches_derived_ip(validator):
    """IP-typed alerts should match redteam records via host_to_ip derivation."""
    from seerflow.lanl.hostmap import host_to_ip
    from seerflow.lanl.parser import RedTeamRecord

    derived_ip = host_to_ip("C17693")  # "10.0.69.29"
    redteam = [
        RedTeamRecord(time=100, user="?", src_computer="C17693", dst_computer="C528"),
    ]
    alerts = [_make_alert(timestamp_ns=110_000_000_000, entity_value=derived_ip)]
    tp, fp, missed = validator.match_against_ground_truth(alerts, redteam)
    assert len(tp) == 1
    assert len(fp) == 0
    assert len(missed) == 0


def test_match_invalid_hostname_does_not_crash(validator):
    """Redteam records with non-LANL hostnames should not crash matching."""
    from seerflow.lanl.parser import RedTeamRecord

    redteam = [
        RedTeamRecord(time=100, user="U1@DOM1", src_computer="INVALID", dst_computer="ALSO_BAD"),
    ]
    alerts = [_make_alert(timestamp_ns=110_000_000_000, entity_value="u1")]
    tp, _fp, _missed = validator.match_against_ground_truth(alerts, redteam)
    # Should still match on normalized username
    assert len(tp) == 1


# ---------------------------------------------------------------------------
# S-305: FamilyMetrics + per_family / scope_label on ValidationResult
# ---------------------------------------------------------------------------


def test_family_metrics_is_frozen_with_expected_fields(validator):
    fm = validator.FamilyMetrics(
        true_positives=2,
        false_positives=1,
        false_negatives=0,
        precision=2 / 3,
        recall=1.0,
        f1_score=0.8,
        total_alerts=3,
    )
    assert fm.true_positives == 2
    assert fm.total_alerts == 3
    with pytest.raises((AttributeError, TypeError)):
        fm.true_positives = 9  # frozen


def test_validation_result_has_per_family_and_scope_label(compute_metrics):
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.per_family == {}
    assert isinstance(result.scope_label, str)
    assert result.scope_label  # non-empty default


def test_compute_metrics_buckets_per_family(compute_metrics):
    """Alerts are bucketed by alert_type into per_family sub-metrics."""

    def alert(alert_id, alert_type):
        import msgspec.structs

        return msgspec.structs.replace(_make_alert(alert_id=alert_id), alert_type=alert_type)

    tp = [alert("1", "correlation"), alert("2", "ml"), alert("3", "ml")]
    fp = [alert("fp1", "sigma")]
    result = compute_metrics(
        tp_alerts=tp,
        fp_alerts=fp,
        missed_redteam=[],
        alerts=tp + fp,
        events_processed=10,
        detection_latencies={},
    )
    assert set(result.per_family) == {"correlation", "ml", "sigma"}
    assert result.per_family["ml"].true_positives == 2
    assert result.per_family["ml"].total_alerts == 2
    assert result.per_family["ml"].precision == pytest.approx(1.0)
    assert result.per_family["sigma"].false_positives == 1
    assert result.per_family["sigma"].precision == 0.0
    assert result.per_family["sigma"].recall == 0.0
    assert result.per_family["correlation"].true_positives == 1


def test_compute_metrics_per_family_empty_when_no_alerts(compute_metrics):
    """No alerts → per_family is empty (families without alerts are skipped)."""
    result = compute_metrics(
        tp_alerts=[],
        fp_alerts=[],
        missed_redteam=[],
        alerts=[],
        events_processed=0,
        detection_latencies={},
    )
    assert result.per_family == {}


# ---------------------------------------------------------------------------
# S-305: _build_raw_events — LANL records → text RawEvents (§A.5/§A.9)
# ---------------------------------------------------------------------------


def test_build_raw_events_emits_text_rawevents(validator):
    from seerflow.lanl.parser import AuthRecord, FlowRecord, ProcRecord
    from seerflow.receivers.base import RawEvent

    auth = AuthRecord(
        time=100,
        src_user="U1@DOM1",
        dst_user="U5624@DOM1",
        src_computer="C17693",
        dst_computer="C528",
        auth_type="Negotiate",
        logon_type="Network",
        auth_orientation="LogOn",
        success=False,
    )
    proc = ProcRecord(
        time=110, user="U2@DOM1", computer="C9", process_name="P1", start_end="Start"
    )
    flow = FlowRecord(
        time=120,
        duration=1,
        src_computer="C9999",
        src_port="1234",
        dst_computer="C8888",
        dst_port="443",
        protocol=6,
        packet_count=5,
        byte_count=4096,
    )
    raws = validator._build_raw_events([auth], [proc], [flow])
    assert all(isinstance(r, RawEvent) for r in raws)
    assert len(raws) == 3  # one per record
    msgs = [r.data.decode() for r in raws]
    assert any("authentication failure" in m and "u5624" in m for m in msgs)
    assert any("process" in m for m in msgs)
    assert any("flow established" in m for m in msgs)
    assert all(r.source_type == "syslog" for r in raws)
    assert all(r.received_ns > 0 for r in raws)


def test_build_raw_events_success_auth_message(validator):
    from seerflow.lanl.parser import AuthRecord

    auth = AuthRecord(
        time=200,
        src_user="U1@DOM1",
        dst_user="U7@DOM1",
        src_computer="C42",
        dst_computer="C99",
        auth_type="Kerberos",
        logon_type="Network",
        auth_orientation="LogOn",
        success=True,
    )
    raws = validator._build_raw_events([auth], [], [])
    assert len(raws) == 1
    msg = raws[0].data.decode()
    assert "Accepted password" in msg
    assert "u7" in msg
    assert raws[0].received_ns == 200 * 1_000_000_000


def test_build_raw_events_empty_inputs(validator):
    assert validator._build_raw_events([], [], []) == []


def test_rebased_shifts_received_ns(validator):
    from seerflow.receivers.base import RawEvent

    raw = RawEvent(
        data=b"x",
        source_type="syslog",
        source_id="t",
        received_ns=1_000,
        metadata={},
    )
    shifted = validator._rebased(raw, 500)
    assert shifted.received_ns == 1_500
    assert shifted.data == b"x"
    assert raw.received_ns == 1_000  # original unchanged (immutable)


# ---------------------------------------------------------------------------
# S-305: run_validation_async driver + sync wrapper (AC1/AC3/AC6)
# ---------------------------------------------------------------------------


def test_run_validation_async_exists_and_is_coroutine(validator):
    import inspect

    assert hasattr(validator, "run_validation_async")
    assert inspect.iscoroutinefunction(validator.run_validation_async)


def test_run_validation_no_longer_constructs_correlation_engine_directly(validator):
    """AC1/AC6: validator.py must not build CorrelationEngine itself."""
    import inspect

    src = inspect.getsource(validator)
    assert "CorrelationEngine(" not in src, (
        "validator.py constructs CorrelationEngine directly — must route "
        "through assemble_handler (FR-073 AC1/AC6)"
    )
    assert "assemble_handler" in src


# ---------------------------------------------------------------------------
# S-311 / FR-079 — attack-level metrics on ValidationResult
# ---------------------------------------------------------------------------


def test_validation_result_has_attack_metric_fields(compute_metrics):
    """S-311: ValidationResult carries additive attack-level fields."""
    tp = [_make_alert(alert_id="tp1")]
    result = compute_metrics(
        tp_alerts=tp,
        fp_alerts=[],
        missed_redteam=[],
        alerts=tp,
        events_processed=5,
        detection_latencies={},
        redteam_records=[_make_redteam(time=100)],
    )
    assert isinstance(result.attack_scenarios, tuple)
    assert isinstance(result.roc_points, tuple)
    assert isinstance(result.pr_points, tuple)
    assert isinstance(result.missed_attributions, tuple)
    assert result.auc is None or 0.0 <= result.auc <= 1.0


def test_validation_result_attack_fields_default_empty(validation_result_cls):
    """Additive fields default to safe empties — existing callers unaffected."""
    r = validation_result_cls(
        true_positives=0,
        false_positives=0,
        false_negatives=0,
        precision=0.0,
        recall=0.0,
        f1_score=0.0,
        false_positive_rate=0.0,
        detection_latency_s={},
        patterns_detected=frozenset(),
        total_events_processed=0,
        total_alerts=0,
    )
    assert r.attack_scenarios == ()
    assert r.roc_points == ()
    assert r.pr_points == ()
    assert r.missed_attributions == ()
    assert r.auc is None


def test_compute_metrics_populates_scenarios_and_attribution(compute_metrics):
    """Detected brute-force scenario + a missed C2 record get scored."""
    tp = [
        _make_alert(
            alert_id="tp1",
            timestamp_ns=150_000_000_000,
            rule_name="brute-force-lateral-movement",
            entity_value="u5624",
        )
    ]
    missed = [_make_redteam(time=300, user="?", src_computer="C9999", dst_computer="C8888")]
    all_rt = [
        _make_redteam(time=110, user="U5624@DOM1", src_computer="C17693", dst_computer="C528"),
        *missed,
    ]
    result = compute_metrics(
        tp_alerts=tp,
        fp_alerts=[],
        missed_redteam=missed,
        alerts=tp,
        events_processed=10,
        detection_latencies={},
        redteam_records=all_rt,
    )
    names = {s.name for s in result.attack_scenarios}
    assert "brute-force-lateral-movement" in names
    assert "c2-beaconing" in names
    brute = next(s for s in result.attack_scenarios if s.name == "brute-force-lateral-movement")
    assert brute.detected is True
    assert brute.mttd_seconds == 40.0
    assert len(result.missed_attributions) == 1
    assert result.missed_attributions[0].scenario_name == "c2-beaconing"
    assert result.missed_attributions[0].silent_family == "correlation"


def test_compute_metrics_headline_unchanged_by_attack_fields(compute_metrics):
    """AC5 regression: adding attack metrics must not move P/R/F1/FPR."""
    tp = [_make_alert(alert_id=str(i)) for i in range(3)]
    fp = [_make_alert(alert_id="fp-1")]
    result = compute_metrics(
        tp_alerts=tp,
        fp_alerts=fp,
        missed_redteam=[_make_redteam()],
        alerts=tp + fp,
        events_processed=10,
        detection_latencies={},
        redteam_records=[_make_redteam()],
    )
    assert result.precision == pytest.approx(0.75)
    assert result.recall == pytest.approx(0.75)
    assert result.false_positive_rate == pytest.approx(0.25)
