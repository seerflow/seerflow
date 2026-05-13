"""Integration tests for ``seerflow export`` (S-076).

Drives a real SQLite-backed storage layer, writes a known event + alert
set, then runs ``run_export`` end-to-end against the live backend. Both
NDJSON (default) and CSV outputs are exercised.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow import export_cmd
from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


class _NoCloseProxy:
    """Forwards everything to the underlying backend except ``close``.

    The integration tests share one ``SqliteBackend`` across multiple
    ``run_export`` invocations; the production code calls ``close`` in
    a ``finally`` block, which would tear down the shared connection
    half-way through the test.
    """

    def __init__(self, inner: SqliteBackend) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def close(self) -> None:
        return None


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    config = StorageConfig(
        backend="sqlite",
        sqlite_path=str(tmp_path / "export_integration.db"),
    )
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


def _make_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "command": "export",
        "export_type": "events",
        "format": "json",
        "since": "1h",
        "source": None,
        "severity": None,
        "limit": 100_000,
        "output": None,
        "type": None,
        "config": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _event(idx: int, *, ts_ns: int) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=ts_ns + idx,
        observed_ns=ts_ns + idx,
        message=f"event message {idx}",
        source_type="auth",
        template_id=idx,
        entity_refs=(str(uuid.uuid4()),),
    )


def _alert(idx: int, *, ts_ns: int) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=ts_ns + idx,
        severity_id=SeverityLevel.WARNING,
        rule_name=f"rule-{idx}",
        description=f"alert description {idx}",
        entity_uuid=str(uuid.uuid4()),
        entity_value=f"10.0.0.{idx}",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=("TA0001",),
        mitre_techniques=("T1059",),
        risk_score=0.75,
        dedup_key=f"export-test-{uuid.uuid4()}",
        dedup_count=1,
    )


@pytest.mark.integration
async def test_export_events_json_end_to_end(
    backend: SqliteBackend,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real SQLite + production write API + run_export with format=json."""
    import time as _time

    now_ns = _time.time_ns()
    events = [_event(i, ts_ns=now_ns - 60_000_000_000 + i * 1_000_000) for i in range(5)]
    await backend.write_events(events)
    await backend.flush()

    async def fake_connect(_args: argparse.Namespace) -> object:
        return _NoCloseProxy(backend)

    monkeypatch.setattr(export_cmd, "_connect_storage_from_args", fake_connect)

    rc = await export_cmd.run_export(_make_args())
    assert rc == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 5
    for line in lines:
        record = json.loads(line)
        assert "event_id" in record
        assert "timestamp_ns" in record
        assert record["source_type"] == "auth"


@pytest.mark.integration
async def test_export_events_csv_end_to_end(
    backend: SqliteBackend,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    now_ns = _time.time_ns()
    events = [_event(i, ts_ns=now_ns - 60_000_000_000 + i * 1_000_000) for i in range(3)]
    await backend.write_events(events)
    await backend.flush()

    async def fake_connect(_args: argparse.Namespace) -> object:
        return _NoCloseProxy(backend)

    monkeypatch.setattr(export_cmd, "_connect_storage_from_args", fake_connect)

    rc = await export_cmd.run_export(_make_args(format="csv"))
    assert rc == 0
    out = capsys.readouterr().out
    rows = list(csv.DictReader(io.StringIO(out)))
    assert len(rows) == 3
    assert rows[0]["source_type"] == "auth"


@pytest.mark.integration
async def test_export_alerts_json_end_to_end(
    backend: SqliteBackend,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    now_ns = _time.time_ns()
    alerts = [_alert(i, ts_ns=now_ns - 30_000_000_000 + i * 1_000_000) for i in range(3)]
    for a in alerts:
        await backend.write_alert(a)

    async def fake_connect(_args: argparse.Namespace) -> object:
        return _NoCloseProxy(backend)

    monkeypatch.setattr(export_cmd, "_connect_storage_from_args", fake_connect)

    rc = await export_cmd.run_export(_make_args(export_type="alerts"))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    record = json.loads(lines[0])
    assert record["type"] == "ml"
    assert record["tactics"] == ["TA0001"]
    assert record["entity_type"] == "ip"


@pytest.mark.integration
async def test_export_events_to_file_end_to_end(
    backend: SqliteBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    now_ns = _time.time_ns()
    events = [_event(i, ts_ns=now_ns - 60_000_000_000 + i * 1_000_000) for i in range(4)]
    await backend.write_events(events)
    await backend.flush()

    target = tmp_path / "events_out.json"

    async def fake_connect(_args: argparse.Namespace) -> object:
        return _NoCloseProxy(backend)

    monkeypatch.setattr(export_cmd, "_connect_storage_from_args", fake_connect)

    rc = await export_cmd.run_export(_make_args(output=str(target)))
    assert rc == 0
    assert target.exists()
    content = target.read_text()
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 4
