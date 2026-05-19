"""Tests for ConsoleSink: stream resolution, severity filter, JSON + human lines."""

from __future__ import annotations

import asyncio
import io
import json
import uuid

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(
    *,
    severity_id: SeverityLevel = SeverityLevel.ERROR,
    rule_name: str = "hst-anomaly",
    description: str = "Anomalous login burst",
    entity_value: str = "10.0.0.1",
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity_id,
        rule_name=rule_name,
        description=description,
        entity_uuid="entity-uuid-001",
        entity_value=entity_value,
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.85,
        dedup_key=f"test:{rule_name}",
    )


def test_resolves_named_stream_to_stringio_when_injected() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    assert sink.bounds() == {"current": 0, "max": 10_000, "evictions": 0}


def test_resolves_string_stdout_to_sys_stdout() -> None:
    import sys

    from seerflow.alerting.sinks.console import ConsoleSink

    sink = ConsoleSink("stdout", fmt="json")
    assert sink._stream is sys.stdout
    sink2 = ConsoleSink("stderr", fmt="human")
    assert sink2._stream is sys.stderr


def test_write_alert_json_emits_one_parseable_object() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    alert = _make_alert()
    sink._write_alert(alert)
    out = buf.getvalue()
    assert out.endswith("\n")
    assert out.count("\n") == 1
    parsed = json.loads(out.strip())
    assert parsed["rule_name"] == "hst-anomaly"
    assert parsed["severity"] == "ERROR"
    assert parsed["entity_value"] == "10.0.0.1"


def test_write_alert_human_line_is_grep_friendly() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="human")
    sink._write_alert(_make_alert())
    out = buf.getvalue()
    assert out.count("\n") == 1
    assert out.startswith("[ERROR] hst-anomaly")
    assert "entity=10.0.0.1 (ip)" in out
    assert "risk=0.85" in out
    assert "Anomalous login burst" in out


def test_write_alert_below_min_severity_is_skipped() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json", min_severity=int(SeverityLevel.CRITICAL))
    sink._write_alert(_make_alert(severity_id=SeverityLevel.WARNING))
    assert buf.getvalue() == ""
    sink._write_alert(_make_alert(severity_id=SeverityLevel.CRITICAL))
    assert buf.getvalue() != ""


def test_invalid_format_rejected() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    with pytest.raises(ValueError, match="fmt"):
        ConsoleSink(io.StringIO(), fmt="xml")  # type: ignore[arg-type]


def test_empty_and_unicode_description_do_not_crash() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    sink._write_alert(_make_alert(description=""))
    sink._write_alert(_make_alert(description="naïve café 日本語 🚨"))
    lines = buf.getvalue().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # each independently valid


async def test_close_is_noop_and_does_not_close_stream() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    await sink.close()
    assert not buf.closed
    sink._write_alert(_make_alert())
    assert buf.getvalue() != ""


async def test_run_writes_within_one_second() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="human")
    task = asyncio.create_task(sink.run())
    sink.enqueue(_make_alert())
    for _ in range(50):
        if buf.getvalue():
            break
        await asyncio.sleep(0.02)
    assert "[ERROR] hst-anomaly" in buf.getvalue()
    await sink.stop()
    await asyncio.wait_for(task, timeout=3.0)


def test_enqueue_overflow_drops_and_counts() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    sink = ConsoleSink(io.StringIO(), fmt="json", queue_maxsize=1)
    sink.enqueue(_make_alert())
    sink.enqueue(_make_alert())  # dropped
    b = sink.bounds()
    assert b["current"] == 1
    assert b["max"] == 1
    assert b["evictions"] == 1


async def test_run_drains_then_exits_on_stop() -> None:
    from seerflow.alerting.sinks.console import ConsoleSink

    buf = io.StringIO()
    sink = ConsoleSink(buf, fmt="json")
    sink.enqueue(_make_alert(rule_name="r1"))
    sink.enqueue(_make_alert(rule_name="r2"))
    task = asyncio.create_task(sink.run())
    await sink.stop()
    await asyncio.wait_for(task, timeout=3.0)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert {line["rule_name"] for line in lines} == {"r1", "r2"}


def test_console_sink_exported_from_package() -> None:
    from seerflow.alerting.sinks import ConsoleSink as Exported
    from seerflow.alerting.sinks.console import ConsoleSink as Direct

    assert Exported is Direct
