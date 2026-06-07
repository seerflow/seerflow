"""Integration: a declared SinkConfig registers on NotificationRouter and
receives a routed alert through the existing dispatch path (S-361/FR-005)."""

from __future__ import annotations

import io
import json
import uuid

import pytest

from seerflow.alerting.router import (
    DefaultRouting,
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from seerflow.alerting.sinks.adapter import build_queue_sink_target
from seerflow.config import SinkConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _alert() -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.CRITICAL,
        rule_name="r-int",
        description="routed via declared sink",
        entity_uuid="e-1",
        entity_value="10.0.0.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.99,
        dedup_key="int:r",
    )


async def test_declared_sink_receives_routed_alert() -> None:
    buf = io.StringIO()
    target = build_queue_sink_target(
        SinkConfig(type="console", name="ops", formatter="json"),
        _stream_override=buf,
    )
    router = NotificationRouter(
        targets=(),
        rules=(
            RoutingRule(
                match=RoutingRuleMatch(),
                notify=(RoutingRuleNotify(channel="ops", mode="immediate"),),
            ),
        ),
        default_routing=DefaultRouting(action="drop"),
    )
    router.register_target(target)  # registers by unique name — no new path
    await router.route(_alert())
    parsed = json.loads(buf.getvalue().strip())
    assert parsed["rule_name"] == "r-int"


async def test_duplicate_registration_rejected() -> None:
    t1 = build_queue_sink_target(SinkConfig(type="console", name="dup", formatter="json"))
    t2 = build_queue_sink_target(SinkConfig(type="console", name="dup", formatter="slack"))
    router = NotificationRouter(targets=(t1,))
    with pytest.raises(ValueError, match="duplicate"):
        router.register_target(t2)
