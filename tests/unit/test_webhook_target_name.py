"""WebhookTarget.name conformance for S-164."""

from __future__ import annotations

import pytest

from seerflow.alerting.dispatcher import WebhookTarget
from seerflow.alerting.target import DeliveryTarget


@pytest.mark.unit
def test_webhook_target_has_name_field() -> None:
    t = WebhookTarget(name="slack", url="https://example.com/wh", format="slack")
    assert t.name == "slack"


@pytest.mark.unit
def test_webhook_target_satisfies_delivery_target_protocol() -> None:
    t = WebhookTarget(name="slack", url="https://example.com/wh", format="slack")
    assert isinstance(t, DeliveryTarget)


@pytest.mark.unit
async def test_webhook_target_deliver_stubs_raise_not_implemented() -> None:
    from tests.unit.alert_factory import make_alert

    t = WebhookTarget(name="slack", url="https://example.com/wh", format="slack")
    alert = make_alert()
    with pytest.raises(NotImplementedError, match="deliver is not called directly"):
        await t.deliver(alert)
    with pytest.raises(NotImplementedError, match="deliver_digest is not called directly"):
        await t.deliver_digest([alert])
