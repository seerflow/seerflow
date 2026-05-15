"""Per-channel quiet hours, including midnight wrap."""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

from seerflow.alerting.router import (
    NotificationRouter,
    QuietHours,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from seerflow.models.event import SeverityLevel
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert


def _clock_at(hh: int, mm: int) -> Callable[[], datetime]:
    return lambda: datetime(2026, 4, 17, hh, mm, tzinfo=UTC)


@pytest.mark.unit
async def test_same_day_window_suppresses_below_min_severity() -> None:
    slack = FakeDeliveryTarget(name="slack")
    router = NotificationRouter(
        targets=(slack,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
            ),
        ),
        quiet_hours_by_channel={
            "slack": QuietHours(start=time(9, 0), end=time(17, 0), min_severity=5)
        },
        now_fn=_clock_at(12, 0),
    )

    await router.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert slack.delivered == []

    await router.route(make_alert(severity_id=SeverityLevel.CRITICAL))
    assert len(slack.delivered) == 1


@pytest.mark.unit
async def test_overnight_wrap() -> None:
    slack = FakeDeliveryTarget(name="slack")

    def router_builder(now: tuple[int, int]) -> NotificationRouter:
        return NotificationRouter(
            targets=(slack,),
            rules=(
                RoutingRule(
                    match=RoutingRuleMatch(),
                    notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
                ),
            ),
            quiet_hours_by_channel={
                "slack": QuietHours(start=time(22, 0), end=time(6, 0), min_severity=5)
            },
            now_fn=_clock_at(*now),
        )

    r1 = router_builder((23, 0))
    await r1.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert slack.delivered == []

    slack.delivered.clear()
    r2 = router_builder((3, 0))
    await r2.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert slack.delivered == []

    r3 = router_builder((8, 0))
    await r3.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert len(slack.delivered) == 1


@pytest.mark.unit
async def test_quiet_hours_per_target_not_global() -> None:
    """A rule dispatches to two channels; only the one with quiet hours drops."""
    slack = FakeDeliveryTarget(name="slack")
    email = FakeDeliveryTarget(name="email")
    router = NotificationRouter(
        targets=(slack, email),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="slack", mode="immediate"),
                    RoutingRuleNotify(channel="email", mode="immediate"),
                ),
            ),
        ),
        quiet_hours_by_channel={
            "slack": QuietHours(start=time(9, 0), end=time(17, 0), min_severity=6)
        },
        now_fn=_clock_at(12, 0),
    )

    await router.route(make_alert(severity_id=SeverityLevel.WARNING))
    assert slack.delivered == []
    assert len(email.delivered) == 1
