"""Tests for SmsTarget — Twilio via raw aiohttp (S-163)."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from seerflow.alerting.channels.sms import SmsTarget, format_sms_body, format_sms_digest
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
def test_format_sms_body_truncates_long_rule_at_1600_chars() -> None:
    alert = make_alert(rule_name="r" * 3000)
    body = format_sms_body(alert)
    assert len(body) <= 1600
    assert body.endswith("…")


@pytest.mark.unit
def test_format_sms_body_under_limit_not_truncated() -> None:
    alert = make_alert(rule_name="short-rule", severity_id=SeverityLevel.ERROR)
    body = format_sms_body(alert)
    assert body.startswith("Seerflow [ERROR]")
    assert "short-rule" in body
    assert not body.endswith("…")


@pytest.mark.unit
def test_format_sms_digest_has_top_alert_and_plus_k_more() -> None:
    alerts = [
        make_alert(rule_name="r-warn", severity_id=SeverityLevel.WARNING),
        make_alert(rule_name="top-rule", severity_id=SeverityLevel.CRITICAL),
        make_alert(rule_name="r-err", severity_id=SeverityLevel.ERROR),
    ]
    body = format_sms_digest(alerts)
    assert "top-rule" in body
    assert "+2 more" in body


@pytest.mark.unit
def test_format_sms_digest_with_single_alert_has_no_tail() -> None:
    alerts = [make_alert(rule_name="only", severity_id=SeverityLevel.CRITICAL)]
    body = format_sms_digest(alerts)
    assert "only" in body
    assert "more" not in body


@pytest.mark.unit
def test_sms_target_hides_auth_token_in_repr() -> None:
    t = SmsTarget(
        name="s",
        account_sid="AC123",
        auth_token="secret-value",
        from_number="+15551234567",
        to_numbers=("+15559876543",),
        rate_per_second=100.0,
        burst=10,
    )
    assert "secret-value" not in repr(t)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_deliver_posts_to_twilio_messages_endpoint() -> None:
    target = SmsTarget(
        name="s",
        account_sid="AC123",
        auth_token="tok",
        from_number="+15551234567",
        to_numbers=("+15559876543",),
        rate_per_second=100.0,
        burst=10,
    )
    with aioresponses() as mock:
        mock.post(
            "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json",
            status=201,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver(make_alert(), session=session)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_deliver_sends_to_each_to_number() -> None:
    target = SmsTarget(
        name="s",
        account_sid="AC1",
        auth_token="tok",
        from_number="+1",
        to_numbers=("+2", "+3"),
        rate_per_second=100.0,
        burst=10,
    )
    calls: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        calls.append(kwargs.get("data") or {})
        return CallbackResult(status=201)

    with aioresponses() as mock:
        mock.post(
            "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json",
            callback=_capture,
            repeat=True,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver(make_alert(), session=session)

    assert len(calls) == 2
    to_values = [c["To"] for c in calls]
    assert "+2" in to_values
    assert "+3" in to_values


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_digest_sends_single_message_per_to_number() -> None:
    target = SmsTarget(
        name="s",
        account_sid="AC1",
        auth_token="tok",
        from_number="+1",
        to_numbers=("+2",),
        rate_per_second=100.0,
        burst=10,
    )
    alerts = [
        make_alert(rule_name="a"),
        make_alert(rule_name="b"),
        make_alert(rule_name="c"),
    ]
    bodies: list[str] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        bodies.append((kwargs.get("data") or {})["Body"])
        return CallbackResult(status=201)

    with aioresponses() as mock:
        mock.post(
            "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json",
            callback=_capture,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver_digest(alerts, session=session)

    assert len(bodies) == 1
    assert "+2 more" in bodies[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sms_empty_digest_does_no_network_io() -> None:
    target = SmsTarget(
        name="s",
        account_sid="AC1",
        auth_token="tok",
        from_number="+1",
        to_numbers=("+2",),
        rate_per_second=100.0,
        burst=10,
    )
    with aioresponses() as mock:
        async with aiohttp.ClientSession() as session:
            await target.deliver_digest([], session=session)
        assert not mock.requests
