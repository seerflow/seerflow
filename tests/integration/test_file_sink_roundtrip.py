"""S-313 integration: FileSink driven through its consumer loop.

Asserts the on-disk NDJSON parses back to the emitted alert, that a forced
size rotation produces multiple files, and that a simulated restart appends
rather than truncating (FR-072 acceptance proof).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.alerting.sinks.file import FileSink
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def _alert(desc: str) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.CRITICAL,
        rule_name="ssh-brute",
        description=desc,
        entity_uuid="entity-uuid-009",
        entity_value="10.1.1.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.95,
        dedup_key="test:ssh-brute",
    )


async def test_enqueued_alerts_roundtrip_from_disk(tmp_path: Path) -> None:
    target = tmp_path / "alerts.ndjson"
    sink = FileSink(str(target))
    task = asyncio.create_task(sink.run())
    for i in range(5):
        sink.enqueue(_alert(f"attempt-{i}"))
    await asyncio.sleep(0.1)
    await sink.stop()
    await task
    await sink.close()

    lines = target.read_text().splitlines()
    assert len(lines) == 5
    parsed = [json.loads(line) for line in lines]
    assert [p["description"] for p in parsed] == [f"attempt-{i}" for i in range(5)]
    assert {p["rule_name"] for p in parsed} == {"ssh-brute"}
    assert {p["severity"] for p in parsed} == {"CRITICAL"}
    assert {p["entity_value"] for p in parsed} == {"10.1.1.9"}


async def test_rotation_and_restart_append(tmp_path: Path) -> None:
    target = tmp_path / "rot.ndjson"
    s1 = FileSink(str(target), rotation="size", max_bytes=300, backup_count=3)
    t1 = asyncio.create_task(s1.run())
    for i in range(40):
        s1.enqueue(_alert(f"long-padded-description-event-{i}-xxxxxxxxxxxxxxxx"))
    await asyncio.sleep(0.2)
    await s1.stop()
    await t1
    await s1.close()

    files_after_run1 = sorted(p.name for p in tmp_path.glob("rot.ndjson*"))
    assert any(name.endswith(".1") for name in files_after_run1)

    before = len((tmp_path / "rot.ndjson").read_text().splitlines())
    s2 = FileSink(str(target), rotation="size", max_bytes=10_000_000)
    t2 = asyncio.create_task(s2.run())
    s2.enqueue(_alert("post-restart"))
    await asyncio.sleep(0.1)
    await s2.stop()
    await t2
    await s2.close()
    after = (tmp_path / "rot.ndjson").read_text().splitlines()
    assert len(after) == before + 1
    assert json.loads(after[-1])["description"] == "post-restart"
