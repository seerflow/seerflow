"""Targeted coverage tests for NotificationRouter edge paths (S-164)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from seerflow.alerting.router import (
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
    _default_utc_now,
)
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
def test_default_utc_now_returns_aware_utc() -> None:
    now = _default_utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


@pytest.mark.unit
def test_duplicate_target_name_rejected() -> None:
    a = FakeDeliveryTarget(name="dup")
    b = FakeDeliveryTarget(name="dup")
    with pytest.raises(ValueError, match="duplicate DeliveryTarget name"):
        NotificationRouter(targets=(a, b))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_route_unknown_channel_logs_and_drops(caplog: pytest.LogCaptureFixture) -> None:
    slack = FakeDeliveryTarget(name="slack")
    router = NotificationRouter(
        targets=(slack,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(RoutingRuleNotify(channel="nowhere", mode="immediate"),),
            ),
        ),
    )
    with caplog.at_level("ERROR"):
        await router.route(make_alert())
    assert slack.delivered == []
    assert any("unknown channel" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_safe_deliver_swallows_target_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    slack = FakeDeliveryTarget(name="slack", deliver_raises=RuntimeError("boom"))
    router = NotificationRouter(
        targets=(slack,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
            ),
        ),
    )
    with caplog.at_level("ERROR"):
        await router.route(make_alert())
    assert any("delivery failed" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_key_deliver_digest_exception_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    email = FakeDeliveryTarget(name="email", digest_raises=RuntimeError("kaboom"))
    router = NotificationRouter(
        targets=(email,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=1),
                ),
            ),
        ),
    )
    await router.start()
    with (
        patch("seerflow.alerting.router.asyncio.sleep", new=AsyncMock()),
        caplog.at_level("ERROR"),
    ):
        await router.route(make_alert(rule_name="r1"))
        # Let the lazily-spawned flusher run to completion.
        await asyncio.wait(list(router._digest_tasks.values()), timeout=1.0)
    # deliver_digest raised; flusher logged it and dropped the buffer.
    assert any("digest delivery failed" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_drain_handles_target_vanishing() -> None:
    """stop()'s final drain pops buffers even if the target is missing."""
    email = FakeDeliveryTarget(name="email")
    router = NotificationRouter(
        targets=(email,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=60),
                ),
            ),
        ),
    )
    await router.start()
    sleep_event = asyncio.Event()

    async def hanging_sleep(_seconds: float) -> None:
        await sleep_event.wait()

    with patch("seerflow.alerting.router.asyncio.sleep", new=hanging_sleep):
        await router.route(make_alert(rule_name="r1"))
        # Simulate the target having vanished between enqueue and stop.
        router._targets.pop("email")
        await router.stop()
    # Buffer was popped without raising; no digest was delivered (target gone).
    assert router._digest_buffers == {}
    assert email.digests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_drain_target_exception_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    email = FakeDeliveryTarget(name="email", digest_raises=RuntimeError("drain-fail"))
    router = NotificationRouter(
        targets=(email,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=60),
                ),
            ),
        ),
    )
    await router.start()
    sleep_event = asyncio.Event()

    async def hanging_sleep(_seconds: float) -> None:
        await sleep_event.wait()

    with (
        patch("seerflow.alerting.router.asyncio.sleep", new=hanging_sleep),
        caplog.at_level("ERROR"),
    ):
        await router.route(make_alert(rule_name="r1"))
        await router.stop()
    assert any("drain digest failed" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_digest_buffer_warns_above_1000_entries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    email = FakeDeliveryTarget(name="email")
    router = NotificationRouter(
        targets=(email,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=60),
                ),
            ),
        ),
    )
    await router.start()
    sleep_event = asyncio.Event()

    async def hanging_sleep(_seconds: float) -> None:
        await sleep_event.wait()

    with (
        patch("seerflow.alerting.router.asyncio.sleep", new=hanging_sleep),
        caplog.at_level("WARNING"),
    ):
        # Pre-seed buffer just below threshold, then push one more to trip the warn.
        router._digest_buffers[(0, "email")] = [make_alert(rule_name=f"r{i}") for i in range(1000)]
        await router.route(make_alert(rule_name="trip"))
        await router.stop()
    assert any("exceeded 1000 entries" in rec.message for rec in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_after_cancelled_returns_early() -> None:
    email = FakeDeliveryTarget(name="email")
    router = NotificationRouter(
        targets=(email,),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=60),
                ),
            ),
        ),
    )
    await router.start()

    async def cancelling_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    with patch("seerflow.alerting.router.asyncio.sleep", new=cancelling_sleep):
        await router.route(make_alert(rule_name="r1"))
        # Task swallows CancelledError and returns; buffer remains for stop() drain.
        await asyncio.wait(list(router._digest_tasks.values()), timeout=1.0)
    # After cancellation-triggered early return, task is gone but buffer unflushed.
    assert email.digests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_key_no_op_when_buffer_empty() -> None:
    """Direct _flush_key call with empty buffer must early-return."""
    email = FakeDeliveryTarget(name="email")
    router = NotificationRouter(targets=(email,))
    await router._flush_key((0, "email"), email)
    assert email.digests == []
