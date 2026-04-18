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
