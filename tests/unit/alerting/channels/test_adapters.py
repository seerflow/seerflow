"""Tests for the session-binding adapter that wraps HTTP channel targets
so they satisfy the session-less ``DeliveryTarget`` protocol (S-163).
"""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from seerflow.alerting.channels import bind_http_channel
from seerflow.alerting.channels.sms import SmsTarget
from seerflow.alerting.channels.telegram import TelegramTarget
from seerflow.alerting.channels.whatsapp import WhatsAppTarget
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
async def test_bind_http_channel_passes_session_to_sms() -> None:
    sms = SmsTarget(
        name="s",
        account_sid="AC1",
        auth_token="t",
        from_number="+1",
        to_numbers=("+2",),
        rate_per_second=100.0,
        burst=10,
    )
    with aioresponses() as mock:
        mock.post(
            "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json",
            status=201,
        )
        async with aiohttp.ClientSession() as session:
            bound = bind_http_channel(sms, session=session)
            assert bound.name == "s"
            assert bound.min_severity == 0
            await bound.deliver(make_alert())


@pytest.mark.unit
async def test_bind_http_channel_forwards_deliver_digest() -> None:
    tg = TelegramTarget(
        name="tg",
        bot_token="t:ABC",
        chat_id="-1",
        rate_per_second=100.0,
        burst=10,
    )
    captured: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        captured.append(kwargs.get("json") or {})
        return CallbackResult(status=200, payload={"ok": True})

    with aioresponses() as mock:
        mock.post(
            "https://api.telegram.org/bott:ABC/sendMessage",
            callback=_capture,
        )
        async with aiohttp.ClientSession() as session:
            bound = bind_http_channel(tg, session=session)
            await bound.deliver_digest([make_alert(), make_alert()])
    assert len(captured) == 1


@pytest.mark.unit
async def test_bind_http_channel_preserves_min_severity() -> None:
    wa = WhatsAppTarget(
        name="wa",
        phone_number_id="PID",
        access_token="t",
        template_name="seerflow_alert",
        language_code="en",
        to_numbers=("+1",),
        min_severity=5,
    )
    async with aiohttp.ClientSession() as session:
        bound = bind_http_channel(wa, session=session)
        assert bound.min_severity == 5
