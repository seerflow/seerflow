"""Tests for TelegramTarget — Bot API sendMessage (S-163)."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses

from seerflow.alerting.channels.telegram import (
    TelegramTarget,
    escape_markdown_v2,
    format_telegram_body,
    format_telegram_digest,
)
from seerflow.models.event import SeverityLevel
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
def test_escape_markdown_v2_escapes_all_reserved_chars() -> None:
    raw = "a_b*c[d]e(f)g~h`i>j#k+l-m=n|o{p}q.r!s"
    escaped = escape_markdown_v2(raw)
    # Every reserved char gets a leading backslash.
    for ch in "_*[]()~`>#+-=|{}.!":
        assert f"\\{ch}" in escaped


@pytest.mark.unit
def test_format_telegram_body_truncates_at_4096() -> None:
    alert = make_alert(rule_name="x" * 5000)
    body = format_telegram_body(alert)
    assert len(body) <= 4096


@pytest.mark.unit
def test_format_telegram_digest_top_ten_with_plus_k_more() -> None:
    alerts = [
        make_alert(rule_name=f"rule-{i}", severity_id=SeverityLevel.WARNING) for i in range(15)
    ]
    body = format_telegram_digest(alerts)
    assert "\\+5 more" in body  # 15 - 10 = 5 beyond top-10
    assert "Seerflow digest" in body


@pytest.mark.unit
def test_format_telegram_digest_under_ten_no_tail() -> None:
    alerts = [make_alert(rule_name=f"r{i}") for i in range(3)]
    body = format_telegram_digest(alerts)
    assert "more" not in body


@pytest.mark.unit
def test_telegram_target_hides_bot_token_in_repr() -> None:
    t = TelegramTarget(
        name="t",
        bot_token="123456:ABC-DEF-secret",
        chat_id="-100",
        rate_per_second=30.0,
        burst=30,
    )
    assert "ABC-DEF-secret" not in repr(t)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telegram_deliver_posts_to_bot_api() -> None:
    target = TelegramTarget(
        name="t",
        bot_token="123456:ABC",
        chat_id="-100",
        rate_per_second=100.0,
        burst=10,
    )
    with aioresponses() as mock:
        mock.post(
            "https://api.telegram.org/bot123456:ABC/sendMessage",
            status=200,
            payload={"ok": True},
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver(make_alert(), session=session)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telegram_deliver_includes_chat_id_and_parse_mode() -> None:
    target = TelegramTarget(
        name="t",
        bot_token="t:ABC",
        chat_id="-1001234567890",
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
            await target.deliver(make_alert(), session=session)

    assert len(captured) == 1
    body = captured[0]
    assert body["chat_id"] == "-1001234567890"
    assert body["parse_mode"] == "MarkdownV2"
    assert "text" in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telegram_digest_single_message_with_tail() -> None:
    target = TelegramTarget(
        name="t",
        bot_token="t:ABC",
        chat_id="-1",
        rate_per_second=100.0,
        burst=10,
    )
    alerts = [make_alert(rule_name=f"rule-{i}") for i in range(15)]
    posted: list[dict[str, Any]] = []

    def _capture(url: str, **kwargs: Any) -> CallbackResult:
        del url
        posted.append(kwargs.get("json") or {})
        return CallbackResult(status=200, payload={"ok": True})

    with aioresponses() as mock:
        mock.post(
            "https://api.telegram.org/bott:ABC/sendMessage",
            callback=_capture,
        )
        async with aiohttp.ClientSession() as session:
            await target.deliver_digest(alerts, session=session)

    assert len(posted) == 1
    assert "\\+5 more" in posted[0]["text"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_telegram_empty_digest_no_network_io() -> None:
    target = TelegramTarget(
        name="t",
        bot_token="t:ABC",
        chat_id="-1",
        rate_per_second=100.0,
        burst=10,
    )
    with aioresponses() as mock:
        async with aiohttp.ClientSession() as session:
            await target.deliver_digest([], session=session)
        assert not mock.requests
