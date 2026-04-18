"""Match predicate matrix for S-164 RoutingRuleMatch."""

from __future__ import annotations

import pytest

from seerflow.alerting.router import (
    RoutingRule,
    RoutingRuleMatch,
    _rule_matches,
)
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
def test_empty_match_is_wildcard() -> None:
    alert = make_alert(alert_type="sigma", rule_name="brute-force-ssh")
    rule = RoutingRule(match=RoutingRuleMatch(), notify=())
    assert _rule_matches(rule, alert) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "predicate,alert_type,expected",
    [
        ("sigma", "sigma", True),
        ("sigma", "ml", False),
        (("sigma", "ml"), "ml", True),
        (("sigma", "ml"), "correlation", False),
    ],
)
def test_alert_type_predicate(
    predicate: object, alert_type: str, expected: bool
) -> None:
    alert = make_alert(alert_type=alert_type)
    rule = RoutingRule(match=RoutingRuleMatch(alert_type=predicate))  # type: ignore[arg-type]
    assert _rule_matches(rule, alert) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "glob,rule_name,expected",
    [
        ("brute-force*", "brute-force-ssh", True),
        ("brute-force*", "password-spray", False),
        ("*ssh*", "brute-force-ssh", True),
        ("exact-match", "exact-match", True),
    ],
)
def test_rule_name_glob(glob: str, rule_name: str, expected: bool) -> None:
    alert = make_alert(rule_name=rule_name)
    rule = RoutingRule(match=RoutingRuleMatch(rule_name=glob))
    assert _rule_matches(rule, alert) is expected


@pytest.mark.unit
def test_entity_type_list() -> None:
    alert = make_alert(entity_type="host")
    rule = RoutingRule(match=RoutingRuleMatch(entity_type=("user", "host")))
    assert _rule_matches(rule, alert) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "severity,min_sev,max_sev,expected",
    [
        (SeverityLevel.WARNING, 3, None, True),   # 3 >= 3
        (SeverityLevel.NOTICE, 3, None, False),   # 2 < 3
        (SeverityLevel.WARNING, None, 3, True),   # 3 <= 3
        (SeverityLevel.ERROR, None, 3, False),    # 4 > 3
        (SeverityLevel.WARNING, 3, 5, True),
        (SeverityLevel.FATAL, 3, 5, False),
    ],
)
def test_severity_bounds(
    severity: SeverityLevel, min_sev: int | None, max_sev: int | None, expected: bool
) -> None:
    alert = make_alert(severity_id=severity)
    rule = RoutingRule(match=RoutingRuleMatch(min_severity=min_sev, max_severity=max_sev))
    assert _rule_matches(rule, alert) is expected


@pytest.mark.unit
def test_combined_predicates_anded() -> None:
    alert = make_alert(alert_type="sigma", rule_name="brute-force-ssh", entity_type="user")
    rule = RoutingRule(
        match=RoutingRuleMatch(
            alert_type="sigma", rule_name="brute-force*", entity_type="user"
        )
    )
    assert _rule_matches(rule, alert) is True

    rule_miss = RoutingRule(
        match=RoutingRuleMatch(
            alert_type="sigma", rule_name="brute-force*", entity_type="ip"
        )
    )
    assert _rule_matches(rule_miss, alert) is False
