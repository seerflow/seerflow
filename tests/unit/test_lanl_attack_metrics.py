"""Unit tests for the LANL attack-level metrics module (S-311 / FR-079).

TDD (RED -> GREEN -> REFACTOR): written before the implementation exists.
Covers scenario grouping, per-scenario MTTD, PR/ROC sweep, trapezoidal AUC,
and missed-event silent-family attribution. Every public function is a pure
function of the matched alert set + rebased red-team records, so the tests
assert determinism explicitly.
"""

from __future__ import annotations

from seerflow.lanl.parser import RedTeamRecord
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _alert(
    *,
    alert_id: str = "a1",
    timestamp_ns: int = 110_000_000_000,
    rule_name: str = "brute-force-lateral-movement",
    alert_type: str = "correlation",
    entity_value: str = "u5624",
    entity_type: str = "user",
    risk_score: float = 0.9,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=timestamp_ns,
        severity_id=SeverityLevel.CRITICAL,
        rule_name=rule_name,
        description="t",
        entity_uuid="u",
        entity_value=entity_value,
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(),
        risk_score=risk_score,
    )


def _rt(
    *,
    time: int,
    user: str = "U5624@DOM1",
    src_computer: str = "C17693",
    dst_computer: str = "C528",
) -> RedTeamRecord:
    return RedTeamRecord(
        time=time, user=user, src_computer=src_computer, dst_computer=dst_computer
    )


# Fixture-shaped red-team set: 3 scenario time-clusters.
_BRUTE = [_rt(time=110, user="U5624@DOM1", src_computer="C17693", dst_computer="C528")]
_CRED = [
    _rt(time=200, user="U100@DOM1", src_computer="C17693", dst_computer="C200"),
    _rt(time=205, user="U105@DOM1", src_computer="C17693", dst_computer="C205"),
    _rt(time=210, user="U110@DOM1", src_computer="C17693", dst_computer="C210"),
]
_C2 = [
    _rt(time=300, user="?", src_computer="C9999", dst_computer="C8888"),
    _rt(time=420, user="?", src_computer="C9999", dst_computer="C8888"),
]
_ALL_RT = _BRUTE + _CRED + _C2


# ---------------------------------------------------------------------------
# Task 1 — scenario grouping + per-scenario MTTD
# ---------------------------------------------------------------------------


def test_group_scenarios_deterministic_and_named():
    from seerflow.lanl.attack_metrics import group_scenarios

    s1 = group_scenarios(_ALL_RT)
    s2 = group_scenarios(_ALL_RT)
    assert [x.name for x in s1] == [x.name for x in s2]  # stable order
    names = {x.name for x in s1}
    assert "brute-force-lateral-movement" in names
    assert "credential-stuffing" in names
    assert "c2-beaconing" in names
    # Sorted by (first_event_time, name)
    times = [x.first_event_time_s for x in s1]
    assert times == sorted(times)


def test_group_scenarios_record_counts():
    from seerflow.lanl.attack_metrics import group_scenarios

    by_name = {x.name: x for x in group_scenarios(_ALL_RT)}
    assert by_name["brute-force-lateral-movement"].record_count == 1
    assert by_name["credential-stuffing"].record_count == 3
    assert by_name["c2-beaconing"].record_count == 2


def test_group_scenarios_empty():
    from seerflow.lanl.attack_metrics import group_scenarios

    assert group_scenarios([]) == ()


def test_scenario_mttd_detected():
    from seerflow.lanl.attack_metrics import group_scenarios, scenario_mttd

    scenario = next(s for s in group_scenarios(_BRUTE) if s.name == "brute-force-lateral-movement")
    # Alert at t=150s covering user u5624; scenario first event at t=110s.
    alert = _alert(timestamp_ns=150_000_000_000, entity_value="u5624")
    assert scenario_mttd(scenario, _BRUTE, [alert]) == 40.0


def test_scenario_mttd_undetected_is_none():
    from seerflow.lanl.attack_metrics import group_scenarios, scenario_mttd

    scenario = next(s for s in group_scenarios(_BRUTE) if s.name == "brute-force-lateral-movement")
    # Alert covers an unrelated entity -> scenario not detected -> None (never 0.0)
    alert = _alert(timestamp_ns=150_000_000_000, entity_value="someone-else")
    assert scenario_mttd(scenario, _BRUTE, [alert]) is None


def test_scenario_mttd_picks_earliest_covering_alert():
    from seerflow.lanl.attack_metrics import group_scenarios, scenario_mttd

    scenario = next(s for s in group_scenarios(_BRUTE) if s.name == "brute-force-lateral-movement")
    late = _alert(alert_id="late", timestamp_ns=300_000_000_000, entity_value="u5624")
    early = _alert(alert_id="early", timestamp_ns=160_000_000_000, entity_value="u5624")
    assert scenario_mttd(scenario, _BRUTE, [late, early]) == 50.0


# ---------------------------------------------------------------------------
# Task 2 — PR / ROC sweep + trapezoidal AUC
# ---------------------------------------------------------------------------


def test_threshold_sweep_points_sorted_and_bounded():
    from seerflow.lanl.attack_metrics import threshold_sweep

    tp = [_alert(alert_id="tp1", risk_score=0.8)]
    fp = [_alert(alert_id="fp1", risk_score=0.3)]
    pr_points, roc_points = threshold_sweep(tp, fp, n_redteam=1)
    # cut-points include sentinels 0.0 and 1.0 plus the distinct scores.
    thresholds = sorted({p[0] for p in roc_points})
    assert 0.0 in thresholds
    assert 1.0 in thresholds
    assert 0.3 in thresholds
    assert 0.8 in thresholds
    for _t, prec, rec in pr_points:
        assert 0.0 <= prec <= 1.0
        assert 0.0 <= rec <= 1.0
    for _t, fpr, tpr in roc_points:
        assert 0.0 <= fpr <= 1.0
        assert 0.0 <= tpr <= 1.0


def test_threshold_sweep_deterministic():
    from seerflow.lanl.attack_metrics import threshold_sweep

    tp = [_alert(alert_id="tp1", risk_score=0.8), _alert(alert_id="tp2", risk_score=0.5)]
    fp = [_alert(alert_id="fp1", risk_score=0.3)]
    a = threshold_sweep(tp, fp, n_redteam=2)
    b = threshold_sweep(tp, fp, n_redteam=2)
    assert a == b


def test_roc_auc_perfect_separator_is_one():
    from seerflow.lanl.attack_metrics import roc_auc, threshold_sweep

    tp = [_alert(alert_id="tp1", risk_score=1.0)]
    fp = [_alert(alert_id="fp1", risk_score=0.0)]
    _pr, roc = threshold_sweep(tp, fp, n_redteam=1)
    auc = roc_auc(roc)
    assert auc is not None
    assert 0.0 <= auc <= 1.0
    assert auc == 1.0


def test_roc_auc_none_when_no_alerts_and_no_redteam():
    from seerflow.lanl.attack_metrics import roc_auc, threshold_sweep

    _pr, roc = threshold_sweep([], [], n_redteam=0)
    assert roc_auc(roc) is None


def test_roc_auc_clamped_and_finite_single_point():
    from seerflow.lanl.attack_metrics import roc_auc, threshold_sweep

    tp = [_alert(alert_id="tp1", risk_score=0.5)]
    _pr, roc = threshold_sweep(tp, [], n_redteam=1)
    auc = roc_auc(roc)
    assert auc is not None
    assert 0.0 <= auc <= 1.0


# ---------------------------------------------------------------------------
# Task 3 — missed-event silent-family attribution
# ---------------------------------------------------------------------------


def test_attribute_missed_names_silent_family():
    from seerflow.lanl.attack_metrics import attribute_missed

    missed = [_C2[0]]  # one C2 record missed
    attrs = attribute_missed(missed)
    assert len(attrs) == 1
    assert attrs[0].scenario_name == "c2-beaconing"
    assert attrs[0].silent_family == "correlation"


def test_attribute_missed_empty():
    from seerflow.lanl.attack_metrics import attribute_missed

    assert attribute_missed([]) == ()


def test_attribute_missed_deterministic_and_complete():
    from seerflow.lanl.attack_metrics import attribute_missed

    a = attribute_missed(_ALL_RT)
    b = attribute_missed(_ALL_RT)
    assert a == b
    assert len(a) == len(_ALL_RT)  # every missed record attributed exactly once
