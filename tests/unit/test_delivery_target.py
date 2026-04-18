"""Contract tests for the DeliveryTarget protocol + default deliver_digest."""

from __future__ import annotations

import pytest

from seerflow.alerting.target import DeliveryTarget, loop_deliver_digest
from tests.support.fake_delivery_target import FakeDeliveryTarget
from tests.unit.alert_factory import make_alert  # existing helper (see existing tests)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_target_is_delivery_target() -> None:
    target: DeliveryTarget = FakeDeliveryTarget(name="t1", min_severity=0)
    assert target.name == "t1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_loop_deliver_digest_calls_deliver_in_order() -> None:
    target = FakeDeliveryTarget(name="t1", min_severity=0)
    a1 = make_alert(rule_name="r1")
    a2 = make_alert(rule_name="r2")

    await loop_deliver_digest(target, [a1, a2])

    assert [a.rule_name for a in target.delivered] == ["r1", "r2"]
    assert target.digests == []  # fallback used deliver(), not deliver_digest
