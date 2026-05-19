"""Tests for FileSink: NDJSON line, severity filter, append, rotation, backpressure.

S-313 / FR-072 — rotating NDJSON file alert sink.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(
    *,
    severity_id: SeverityLevel = SeverityLevel.CRITICAL,
    rule_name: str = "rule-x",
    description: str = "boom",
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
        risk_score=0.9,
        dedup_key=f"test:{rule_name}",
    )


def test_write_alert_appends_one_ndjson_object(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "alerts.ndjson"
    sink = FileSink(str(target))
    sink._write_alert(_make_alert())
    sink._close_handler()

    lines = target.read_text().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["rule_name"] == "rule-x"
    assert obj["entity_value"] == "10.0.0.1"
    assert obj["severity"] == "CRITICAL"


def test_severity_floor_skips_low_alerts(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "a.ndjson"
    sink = FileSink(str(target), min_severity=int(SeverityLevel.ERROR))
    sink._write_alert(_make_alert(severity_id=SeverityLevel.WARNING))
    sink._write_alert(_make_alert(severity_id=SeverityLevel.CRITICAL))
    sink._close_handler()
    assert len(target.read_text().splitlines()) == 1


def test_reopen_appends_not_truncates(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "a.ndjson"
    s1 = FileSink(str(target))
    s1._write_alert(_make_alert(description="first"))
    s1._close_handler()
    s2 = FileSink(str(target))
    s2._write_alert(_make_alert(description="second"))
    s2._close_handler()
    lines = target.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["description"] == "first"
    assert json.loads(lines[1])["description"] == "second"


async def test_size_rotation_produces_backup_files(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "r.ndjson"
    sink = FileSink(str(target), rotation="size", max_bytes=200, backup_count=3)
    for i in range(50):
        sink._write_alert(_make_alert(description=f"event-number-{i}-padding-to-grow-the-line"))
    sink._close_handler()
    rotated = sorted(p.name for p in tmp_path.glob("r.ndjson*"))
    assert "r.ndjson" in rotated
    assert any(name.endswith(".1") for name in rotated)


def test_enqueue_drops_and_counts_when_full(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    sink = FileSink(str(tmp_path / "q.ndjson"), queue_maxsize=1)
    sink.enqueue(_make_alert())
    sink.enqueue(_make_alert())  # second is dropped
    b = sink.bounds()
    assert b["max"] == 1
    assert b["evictions"] == 1
    assert b["current"] == 1


async def test_run_consumes_and_stop_drains(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "loop.ndjson"
    sink = FileSink(str(target))
    task = asyncio.create_task(sink.run())
    sink.enqueue(_make_alert(description="one"))
    sink.enqueue(_make_alert(description="two"))
    await asyncio.sleep(0.05)
    await sink.stop()
    await task
    await sink.close()
    assert len(target.read_text().splitlines()) == 2


def test_invalid_rotation_raises(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    with pytest.raises(ValueError, match="rotation must be"):
        FileSink(str(tmp_path / "x.ndjson"), rotation="hourly")  # type: ignore[arg-type]


def test_exported_from_sinks_package() -> None:
    from seerflow.alerting.sinks import FileSink as Exported
    from seerflow.alerting.sinks.file import FileSink

    assert Exported is FileSink


async def test_time_rotation_constructs(tmp_path: Path) -> None:
    from seerflow.alerting.sinks.file import FileSink

    target = tmp_path / "t.ndjson"
    sink = FileSink(str(target), rotation="time", interval_seconds=3600)
    sink._write_alert(_make_alert(description="time-rotated"))
    sink._close_handler()
    assert json.loads(target.read_text().splitlines()[0])["description"] == "time-rotated"
