"""First-match-wins ordering for NotificationRouter."""

from __future__ import annotations

import pytest

from seerflow.alerting.router import (
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
async def test_first_matching_rule_wins() -> None:
    slack = FakeDeliveryTarget(name="slack")
    email = FakeDeliveryTarget(name="email")
    rules = (
        RoutingRule(
            match=RoutingRuleMatch(alert_type="sigma"),
            notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
        ),
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(RoutingRuleNotify(channel="email", mode="immediate"),),
        ),
    )
    router = NotificationRouter(targets=(slack, email), rules=rules)

    await router.route(make_alert(alert_type="sigma"))

    assert len(slack.delivered) == 1
    assert email.delivered == []


@pytest.mark.unit
async def test_empty_notify_is_explicit_drop() -> None:
    slack = FakeDeliveryTarget(name="slack")
    email = FakeDeliveryTarget(name="email")
    rules = (
        RoutingRule(match=RoutingRuleMatch(alert_type="sigma"), notify=()),
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(RoutingRuleNotify(channel="email"),),
        ),
    )
    router = NotificationRouter(targets=(slack, email), rules=rules)

    await router.route(make_alert(alert_type="sigma"))

    assert slack.delivered == []
    assert email.delivered == []


@pytest.mark.unit
async def test_per_target_min_severity_still_applies() -> None:
    slack = FakeDeliveryTarget(name="slack", min_severity=5)  # CRITICAL+
    rules = (
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(RoutingRuleNotify(channel="slack"),),
        ),
    )
    router = NotificationRouter(targets=(slack,), rules=rules)

    from seerflow.models.event import SeverityLevel

    await router.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert slack.delivered == []

    await router.route(make_alert(severity_id=SeverityLevel.CRITICAL))
    assert len(slack.delivered) == 1
