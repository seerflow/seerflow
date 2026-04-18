"""Digest buffering and flushing for NotificationRouter."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

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
@pytest.mark.asyncio
async def test_digest_buffers_and_flushes_once_on_window() -> None:
    email = FakeDeliveryTarget(name="email")
    rules = (
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=1),),
        ),
    )
    router = NotificationRouter(targets=(email,), rules=rules)
    await router.start()

    with patch("seerflow.alerting.router.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await router.route(make_alert(rule_name="a"))
        await router.route(make_alert(rule_name="b"))
        await router.route(make_alert(rule_name="c"))
        # Drain the flusher task(s). asyncio.wait does not go through
        # asyncio.sleep, so it yields cleanly under the patch.
        tasks = list(router._digest_tasks.values())
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)
        await router.stop()

    assert email.delivered == []
    assert len(email.digests) == 1
    assert [a.rule_name for a in email.digests[0]] == ["a", "b", "c"]
    sleep_mock.assert_awaited_once_with(60)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_flushes_pending_buffers() -> None:
    email = FakeDeliveryTarget(name="email")
    rules = (
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=60),),
        ),
    )
    router = NotificationRouter(targets=(email,), rules=rules)
    await router.start()

    sleep_event = asyncio.Event()

    async def hanging_sleep(_seconds: float) -> None:
        await sleep_event.wait()

    with patch("seerflow.alerting.router.asyncio.sleep", new=hanging_sleep):
        await router.route(make_alert(rule_name="buffered"))
        await router.stop()

    assert email.digests and email.digests[0][0].rule_name == "buffered"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_immediate_and_digest_are_isolated() -> None:
    slack = FakeDeliveryTarget(name="slack")
    email = FakeDeliveryTarget(name="email")
    rules = (
        RoutingRule(
            match=RoutingRuleMatch(),
            notify=(
                RoutingRuleNotify(channel="slack", mode="immediate"),
                RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=5),
            ),
        ),
    )
    router = NotificationRouter(targets=(slack, email), rules=rules)
    await router.start()

    with patch("seerflow.alerting.router.asyncio.sleep", new=AsyncMock()):
        await router.route(make_alert(rule_name="x"))
        tasks = list(router._digest_tasks.values())
        if tasks:
            await asyncio.wait(tasks, timeout=1.0)
        await router.stop()

    assert len(slack.delivered) == 1
    assert email.delivered == []
    assert len(email.digests) == 1 and email.digests[0][0].rule_name == "x"
