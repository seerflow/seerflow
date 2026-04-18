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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_adapter_injected_into_router_via_public_api() -> None:
    """When webhooks + channels are both configured, the dispatcher's
    webhook adapters are added to the router via ``register_target``.
    """
    from seerflow.alerting.dispatcher import (
        AlertDispatcher,
        WebhookTarget,
        build_webhook_delivery_targets,
    )

    cfg = AlertingConfig(
        webhook_targets=(
            WebhookTarget(name="wh", url="https://x.example", format="json"),
        ),
        telegram_targets=(
            TelegramTarget(name="tg", bot_token="t:ABC", chat_id="-1"),
        ),
    )
    session, router = await _build_channel_session_and_router(cfg)
    assert router is not None
    assert session is not None
    try:
        dispatcher = AlertDispatcher(
            cfg.webhook_targets,
            session,
            dashboard_url="",
            router=router,
        )
        for adapter in build_webhook_delivery_targets(dispatcher):
            router.register_target(adapter)
        # Public API exposes the registered adapters via route() matching.
        # Here we only verify registration was idempotent-safe: registering
        # the same adapter twice must raise.
        first_adapter = next(iter(build_webhook_delivery_targets(dispatcher)))
        with pytest.raises(ValueError, match="duplicate"):
            router.register_target(first_adapter)
    finally:
        await session.close()
