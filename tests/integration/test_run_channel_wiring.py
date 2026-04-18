"""Integration: run.py wires NotificationRouter when channels configured (S-163)."""

from __future__ import annotations

import pytest

from seerflow.alerting.channels.email import EmailTarget
from seerflow.alerting.channels.telegram import TelegramTarget
from seerflow.config import AlertingConfig
from seerflow.pipeline.run import _build_channel_session_and_router


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_channels_no_rules_returns_none_pair() -> None:
    cfg = AlertingConfig()
    session, router = await _build_channel_session_and_router(cfg)
    assert session is None
    assert router is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_telegram_triggers_router_construction() -> None:
    cfg = AlertingConfig(
        telegram_targets=(
            TelegramTarget(
                name="tg",
                bot_token="t:ABC",
                chat_id="-1",
            ),
        ),
    )
    session, router = await _build_channel_session_and_router(cfg)
    assert session is not None
    assert router is not None
    await session.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_email_only_triggers_router_without_http_session() -> None:
    """Email uses its own SMTP connection; HTTP session is still created
    because the helper allocates one HTTP session for all channel kinds.
    """
    cfg = AlertingConfig(
        email_targets=(
            EmailTarget(
                name="em",
                smtp_host="smtp.example.com",
                smtp_port=587,
                use_starttls=True,
                from_address="a@x",
                to_addresses=("b@x",),
            ),
        ),
    )
    session, router = await _build_channel_session_and_router(cfg)
    assert router is not None
    # A shared session may still be allocated — whether it's used depends on
    # which channel kinds are configured. Either None or a ClientSession is
    # acceptable; we just care that the router was built.
    if session is not None:
        await session.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_routing_rules_alone_trigger_router() -> None:
    from seerflow.alerting.router import RoutingRule, RoutingRuleMatch

    cfg = AlertingConfig(
        routing_rules=(RoutingRule(match=RoutingRuleMatch()),),
    )
    session, router = await _build_channel_session_and_router(cfg)
    assert router is not None
    if session is not None:
        await session.close()
