"""End-to-end: enqueue alert → AlertDispatcher → NotificationRouter → targets."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from seerflow.alerting.dispatcher import AlertDispatcher, WebhookTarget
from seerflow.alerting.router import (
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from seerflow.models.event import SeverityLevel
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert


@pytest.mark.integration
async def test_end_to_end_routes_and_digests() -> None:
    slack = FakeDeliveryTarget(name="slack")
    email = FakeDeliveryTarget(name="email")

    router = NotificationRouter(
        targets=(slack, email),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(alert_type="sigma"),
                notify=(RoutingRuleNotify(channel="slack", mode="immediate"),),
            ),
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(
                    RoutingRuleNotify(channel="email", mode="digest", digest_window_minutes=1),
                ),
            ),
        ),
    )
    await router.start()

    session = AsyncMock(spec=aiohttp.ClientSession)
    dispatcher = AlertDispatcher(
        targets=(
            WebhookTarget(name="slack", url="https://x/h", format="json"),
            WebhookTarget(name="email", url="https://y/h", format="json"),
        ),
        session=session,
        router=router,
    )

    dispatcher.enqueue(
        make_alert(
            alert_type="sigma",
            rule_name="brute-force-ssh",
            severity_id=SeverityLevel.ERROR,
        )
    )
    dispatcher.enqueue(
        make_alert(alert_type="ml", rule_name="m1", severity_id=SeverityLevel.WARNING)
    )
    dispatcher.enqueue(
        make_alert(alert_type="ml", rule_name="m2", severity_id=SeverityLevel.WARNING)
    )

    # Gate the flusher so both ml alerts land in the same buffer before any
    # flush fires. router.stop() cancels the flusher and drains the buffer.
    gate = asyncio.Event()

    async def gated_sleep(_seconds: float) -> None:
        await gate.wait()

    with patch("seerflow.alerting.router.asyncio.sleep", new=gated_sleep):
        await dispatcher.stop()
        # dispatcher.run() drains the queue, then calls router.stop() which
        # cancels the gated flusher and drains the accumulated buffer.
        await dispatcher.run()

    assert len(slack.delivered) == 1
    assert email.delivered == []
    assert len(email.digests) == 1
    assert [a.rule_name for a in email.digests[0]] == ["m1", "m2"]
    session.post.assert_not_called()
