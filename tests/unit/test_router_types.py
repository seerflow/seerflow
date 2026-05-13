"""Frozen structural dataclasses for routing rules."""

from __future__ import annotations

from datetime import time

import pytest

from seerflow.alerting.router import (
    DefaultRouting,
    QuietHours,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)


@pytest.mark.unit
def test_match_defaults_are_wildcards() -> None:
    m = RoutingRuleMatch()
    assert m.alert_type is None
    assert m.rule_name is None
    assert m.entity_type is None
    assert m.min_severity is None
    assert m.max_severity is None


@pytest.mark.unit
def test_rule_is_frozen() -> None:
    rule = RoutingRule(match=RoutingRuleMatch(), notify=())
    with pytest.raises(AttributeError):
        rule.notify = ()  # type: ignore[misc]


@pytest.mark.unit
def test_notify_mode_literals() -> None:
    n = RoutingRuleNotify(channel="slack", mode="digest", digest_window_minutes=30)
    assert n.mode == "digest"
    assert n.digest_window_minutes == 30


@pytest.mark.unit
def test_default_routing_and_quiet_hours_compose() -> None:
    dr = DefaultRouting(action="drop", notify=())
    qh = QuietHours(start=time(22, 0), end=time(6, 0), min_severity=5)
    assert dr.action == "drop"
    assert qh.min_severity == 5
