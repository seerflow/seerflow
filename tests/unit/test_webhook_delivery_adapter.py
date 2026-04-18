"""Coverage for _WebhookDeliveryAdapter + build_webhook_delivery_targets (S-164)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiohttp
import pytest

from seerflow.alerting.dispatcher import (
    AlertDispatcher,
    WebhookTarget,
    _WebhookDeliveryAdapter,
    build_webhook_delivery_targets,
)
from tests.unit.alert_factory import make_alert


@pytest.mark.unit
@pytest.mark.asyncio
async def test_adapter_deliver_invokes_dispatcher_retry_path() -> None:
    t = WebhookTarget(name="slack", url="https://example.com/hook", format="json")
    session = AsyncMock(spec=aiohttp.ClientSession)
    dispatcher = AlertDispatcher(targets=(t,), session=session)
    dispatcher._post_with_retry = AsyncMock()  # type: ignore[method-assign]

    adapters = build_webhook_delivery_targets(dispatcher)
    assert len(adapters) == 1
    adapter = adapters[0]
    assert isinstance(adapter, _WebhookDeliveryAdapter)
    assert adapter.name == "slack"

    alert = make_alert()
    await adapter.deliver(alert)

    dispatcher._post_with_retry.assert_awaited_once()
    call_target, _payload, call_alert_id = dispatcher._post_with_retry.await_args.args
    assert call_target is t
    assert call_alert_id == alert.alert_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_adapter_deliver_digest_loops_deliver() -> None:
    t = WebhookTarget(name="slack", url="https://example.com/hook", format="json")
    session = AsyncMock(spec=aiohttp.ClientSession)
    dispatcher = AlertDispatcher(targets=(t,), session=session)
    dispatcher._post_with_retry = AsyncMock()  # type: ignore[method-assign]

    adapter = build_webhook_delivery_targets(dispatcher)[0]
    alerts = [make_alert(rule_name="a"), make_alert(rule_name="b")]
    await adapter.deliver_digest(alerts)

    assert dispatcher._post_with_retry.await_count == 2
