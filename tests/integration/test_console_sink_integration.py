"""Integration: ConsoleSink emits NDJSON that round-trips (S-312/FR-071)."""

from __future__ import annotations

import asyncio
import io
import json
import uuid

from seerflow.alerting.sinks.console import ConsoleSink
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _alert(rule: str) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.CRITICAL,
        rule_name=rule,
        description="integration alert",
        entity_uuid="e-1",
        entity_value="10.0.0.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.99,
        dedup_key=f"int:{rule}",
    )


async def test_ndjson_round_trips_through_running_sink() -> None:
    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    task = asyncio.create_task(sink.run())
    sink.enqueue(_alert("r-a"))
    sink.enqueue(_alert("r-b"))
    await sink.stop()
    await asyncio.wait_for(task, timeout=3.0)

    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]  # each line independently valid
    assert {p["rule_name"] for p in parsed} == {"r-a", "r-b"}
    assert all(p["severity"] == "CRITICAL" for p in parsed)


async def test_assembly_console_sink_disabled_by_default() -> None:
    from seerflow.config import SeerflowConfig
    from seerflow.pipeline.assembly import _build_console_sink

    sink, server_task = _build_console_sink(SeerflowConfig())
    assert sink is None
    assert server_task is None


async def test_assembly_console_sink_built_and_torn_down() -> None:
    from seerflow.config import AlertingConfig, SeerflowConfig
    from seerflow.pipeline.assembly import _build_console_sink

    cfg = SeerflowConfig(alerting=AlertingConfig(console_enabled=True, console_format="json"))
    sink, task = _build_console_sink(cfg)
    assert sink is not None
    assert task is not None
    try:
        sink.enqueue(_alert("assembled"))
        await sink.stop()
        await asyncio.wait_for(task, timeout=3.0)
        await sink.close()
    finally:
        if not task.done():
            task.cancel()
