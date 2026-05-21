"""default_routing behaviour for unmatched alerts."""

from __future__ import annotations

import pytest

from seerflow.alerting.router import (
    DefaultRouting,
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
async def test_default_drop_when_no_rule_matches() -> None:
    slack = FakeDeliveryTarget(name="slack")
    rules = (RoutingRule(match=RoutingRuleMatch(alert_type="correlation"), notify=()),)
    router = NotificationRouter(
        targets=(slack,), rules=rules, default_routing=DefaultRouting(action="drop")
    )

    await router.route(make_alert(alert_type="sigma"))

    assert slack.delivered == []


@pytest.mark.unit
async def test_default_notify_when_no_rule_matches() -> None:
    slack = FakeDeliveryTarget(name="slack")
    rules = (RoutingRule(match=RoutingRuleMatch(alert_type="correlation"), notify=()),)
    router = NotificationRouter(
        targets=(slack,),
        rules=rules,
        default_routing=DefaultRouting(
            action="notify",
            notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
        ),
    )

    await router.route(make_alert(alert_type="sigma"))

    assert len(slack.delivered) == 1


@pytest.mark.unit
async def test_default_absent_with_no_rules_is_drop() -> None:
    slack = FakeDeliveryTarget(name="slack")
    router = NotificationRouter(targets=(slack,), rules=())

    await router.route(make_alert())

    assert slack.delivered == []
