"""Tests for the queue-backed-sink DeliveryTarget adapter (S-361/FR-005)."""

from __future__ import annotations

import io
import json
import uuid

import pytest

from seerflow.alerting.sinks.adapter import build_queue_sink_target
from seerflow.alerting.target import DeliveryTarget
from seerflow.config import SinkConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _alert(rule: str) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.CRITICAL,
        rule_name=rule,
        description="adapter alert",
        entity_uuid="e-1",
        entity_value="10.0.0.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.99,
        dedup_key=f"a:{rule}",
    )


def test_console_target_satisfies_protocol() -> None:
    target = build_queue_sink_target(
        SinkConfig(type="console", name="ops", formatter="json", min_severity=2)
    )
    assert isinstance(target, DeliveryTarget)
    assert target.name == "ops"
    assert target.min_severity == 2


async def test_console_target_deliver_writes_line() -> None:
    buf = io.StringIO()
    target = build_queue_sink_target(
        SinkConfig(type="console", name="ops", formatter="json"),
        _stream_override=buf,
    )
    await target.deliver(_alert("r-a"))
    parsed = json.loads(buf.getvalue().strip())
    assert parsed["rule_name"] == "r-a"


async def test_console_target_deliver_digest_writes_each() -> None:
    buf = io.StringIO()
    target = build_queue_sink_target(
        SinkConfig(type="console", name="ops", formatter="json"),
        _stream_override=buf,
    )
    await target.deliver_digest((_alert("r-a"), _alert("r-b")))
    rules = {json.loads(line)["rule_name"] for line in buf.getvalue().splitlines()}
    assert rules == {"r-a", "r-b"}


async def test_file_target_writes_ndjson(tmp_path: object) -> None:
    out = f"{tmp_path}/alerts.ndjson"  # type: ignore[str-bytes-safe]
    target = build_queue_sink_target(
        SinkConfig(type="file", name="f1", formatter="json", options=(("path", out),))
    )
    await target.deliver(_alert("r-f"))
    with open(out, encoding="utf-8") as fh:
        parsed = json.loads(fh.readline().strip())
    assert parsed["rule_name"] == "r-f"


def test_file_target_requires_path() -> None:
    with pytest.raises(ValueError, match="path"):
        build_queue_sink_target(SinkConfig(type="file", name="f1", formatter="json"))
