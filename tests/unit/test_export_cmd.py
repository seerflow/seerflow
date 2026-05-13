"""Unit tests for ``seerflow export`` CLI command (S-076, FR-045)."""

from __future__ import annotations

import argparse
import csv
import io
import json
import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow import export_cmd
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery, EventQuery, Page


def _event(idx: int = 0, *, entity_refs: tuple[str, ...] = ()) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        observed_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        message=f"event {idx}",
        source_type="auth",
        template_id=idx,
        entity_refs=entity_refs,
    )


def _alert(idx: int = 0) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name=f"rule-{idx}",
        description=f"alert {idx}",
        entity_uuid=str(uuid.uuid4()),
        entity_value=f"value-{idx}",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=("TA0001", "TA0002"),
        mitre_techniques=("T1059",),
        risk_score=0.75,
        dedup_count=3,
    )


class _FakeStorage:
    """In-memory storage stub with page-based responses."""

    def __init__(
        self,
        events: list[SeerflowEvent] | None = None,
        alerts: list[Alert] | None = None,
    ) -> None:
        self._events = events or []
        self._alerts = alerts or []
        self.event_queries: list[EventQuery] = []
        self.alert_queries: list[AlertQuery] = []
        self.closed = False

    async def query_events(self, query: EventQuery) -> Page[SeerflowEvent]:
        self.event_queries.append(query)
        total = len(self._events)
        start = (query.page - 1) * query.limit
        end = start + query.limit
        return Page(
            items=tuple(self._events[start:end]),
            total=total,
            page=query.page,
            limit=query.limit,
        )

    async def query_alerts(self, query: AlertQuery) -> Page[Alert]:
        self.alert_queries.append(query)
        # Apply alert_type / severity_min filters in the stub so we can
        # assert filter wiring without spinning up real SQLite.
        items = self._alerts
        if query.alert_type is not None:
            items = [a for a in items if a.alert_type == query.alert_type]
        if query.severity_min is not None:
            items = [a for a in items if int(a.severity_id) >= query.severity_min]
        total = len(items)
        start = (query.page - 1) * query.limit
        end = start + query.limit
        return Page(
            items=tuple(items[start:end]),
            total=total,
            page=query.page,
            limit=query.limit,
        )

    async def close(self) -> None:
        self.closed = True


def _args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "command": "export",
        "export_type": "events",
        "format": "json",
        "since": "24h",
        "source": None,
        "severity": None,
        "limit": 100,
        "output": None,
        "type": None,
        "config": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Events export
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_export_events_json_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i, entity_refs=(str(uuid.uuid4()),)) for i in range(3)]
    storage = _FakeStorage(events=events)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=3))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        record = json.loads(line)
        assert "event_id" in record
        assert "timestamp_ns" in record
        assert "severity" in record
        assert "source_type" in record
        assert "template_id" in record
        assert "message" in record
        assert "entity_refs" in record
    assert storage.closed is True


@pytest.mark.unit
async def test_export_events_paged_streams_all_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i) for i in range(1250)]
    storage = _FakeStorage(events=events)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=2000))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1250
    # Two pages were issued (1000 + 250).
    assert len(storage.event_queries) == 2
    assert storage.event_queries[0].page == 1
    assert storage.event_queries[1].page == 2
    assert storage.event_queries[0].limit == export_cmd._EXPORT_PAGE_SIZE


@pytest.mark.unit
async def test_export_events_csv_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i, entity_refs=("aaa-bbb", "ccc-ddd")) for i in range(3)]
    storage = _FakeStorage(events=events)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(format="csv", limit=3))
    assert rc == 0
    out = capsys.readouterr().out
    reader = csv.DictReader(io.StringIO(out))
    rows = list(reader)
    assert len(rows) == 3
    expected_cols = {
        "event_id",
        "timestamp_ns",
        "severity",
        "source_type",
        "template_id",
        "entity_refs",
        "message",
    }
    assert expected_cols <= set(rows[0].keys())
    # entity_refs are semicolon-joined.
    assert rows[0]["entity_refs"] == "aaa-bbb;ccc-ddd"


@pytest.mark.unit
async def test_export_events_to_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i) for i in range(2)]
    storage = _FakeStorage(events=events)
    target = tmp_path / "events.json"
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(output=str(target), limit=2))
    assert rc == 0
    assert target.exists()
    content = target.read_text()
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) == 2
    json.loads(lines[0])  # parses


@pytest.mark.unit
async def test_export_events_progress_to_stderr_when_tty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i) for i in range(3)]
    storage = _FakeStorage(events=events)
    with (
        patch.object(export_cmd, "_connect_storage_from_args") as conn,
        patch.object(export_cmd, "_is_tty", return_value=True),
    ):
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=3))
    assert rc == 0
    err = capsys.readouterr().err
    assert "events" in err.lower()


@pytest.mark.unit
async def test_export_events_no_progress_when_not_tty(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i) for i in range(3)]
    storage = _FakeStorage(events=events)
    with (
        patch.object(export_cmd, "_connect_storage_from_args") as conn,
        patch.object(export_cmd, "_is_tty", return_value=False),
    ):
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=3))
    assert rc == 0
    err = capsys.readouterr().err
    # No carriage-return progress when stderr is not a TTY.
    assert "\r" not in err


@pytest.mark.unit
async def test_export_events_bad_since_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = _FakeStorage()
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(since="garbage"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "Invalid duration" in err or "duration" in err.lower()


@pytest.mark.unit
async def test_export_events_bad_severity_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = _FakeStorage()
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(severity=99))
    assert rc == 2
    err = capsys.readouterr().err
    assert "severity" in err.lower()


@pytest.mark.unit
async def test_export_events_unwritable_output_returns_2(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    storage = _FakeStorage()
    # Use a nested non-existent parent directory.
    target = tmp_path / "no-such-dir" / "out.json"
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(output=str(target)))
    assert rc == 2


@pytest.mark.unit
async def test_export_events_filters_passed_to_query(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = [_event(i) for i in range(2)]
    storage = _FakeStorage(events=events)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(
            _args(source="auth", severity=3, limit=2),
        )
    assert rc == 0
    assert len(storage.event_queries) == 1
    q = storage.event_queries[0]
    assert q.source_type == "auth"
    assert q.severity_min == 3
    assert q.time_range is not None


# ---------------------------------------------------------------------------
# Alerts export
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_export_alerts_json_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    alerts = [_alert(i) for i in range(2)]
    storage = _FakeStorage(alerts=alerts)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(export_type="alerts", limit=2))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 2
    record = json.loads(lines[0])
    for key in (
        "alert_id",
        "timestamp_ns",
        "severity",
        "type",
        "score",
        "rule",
        "description",
        "entity_uuid",
        "entity_type",
        "entity_value",
        "tactics",
        "techniques",
        "dedup_count",
    ):
        assert key in record, f"missing {key}"
    assert record["type"] == "ml"
    assert record["tactics"] == ["TA0001", "TA0002"]


@pytest.mark.unit
async def test_export_alerts_csv(
    capsys: pytest.CaptureFixture[str],
) -> None:
    alerts = [_alert(i) for i in range(2)]
    storage = _FakeStorage(alerts=alerts)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(
            _args(export_type="alerts", format="csv", limit=2),
        )
    assert rc == 0
    out = capsys.readouterr().out
    reader = csv.DictReader(io.StringIO(out))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["tactics"] == "TA0001;TA0002"
    assert rows[0]["techniques"] == "T1059"


@pytest.mark.unit
async def test_export_alerts_filtered_by_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    alerts = [_alert(i) for i in range(3)]
    storage = _FakeStorage(alerts=alerts)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(
            _args(export_type="alerts", type="ml", severity=3, limit=3),
        )
    assert rc == 0
    assert len(storage.alert_queries) >= 1
    q = storage.alert_queries[0]
    assert q.alert_type == "ml"
    assert q.severity_min == 3
    assert q.time_range is not None


@pytest.mark.unit
async def test_export_unknown_type_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = _FakeStorage()
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(export_type="bogus"))
    assert rc == 2


@pytest.mark.unit
async def test_export_events_empty_storage_returns_zero_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty storage → run_export emits zero rows and exits 0."""
    storage = _FakeStorage()
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args())
    assert rc == 0
    assert capsys.readouterr().out == ""


@pytest.mark.unit
async def test_export_alerts_empty_storage_returns_zero_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty alert storage → run_export emits zero rows and exits 0."""
    storage = _FakeStorage()
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(export_type="alerts"))
    assert rc == 0
    assert capsys.readouterr().out == ""


@pytest.mark.unit
async def test_export_default_limit_when_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``args.limit = None`` falls back to ``_DEFAULT_LIMIT``."""
    storage = _FakeStorage(events=[_event(0)])
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=None))
    assert rc == 0
    out = capsys.readouterr().out
    assert "event_id" in out


@pytest.mark.unit
async def test_export_progress_csv_event_branch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSV event progress branch fires after every ``_PROGRESS_EVERY`` rows."""
    # Lower the progress threshold so we don't need 1000 fixtures.
    monkeypatch.setattr(export_cmd, "_PROGRESS_EVERY", 2)
    monkeypatch.setattr(export_cmd, "_is_tty", lambda: True)
    storage = _FakeStorage(events=[_event(i) for i in range(2)])
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(format="csv", limit=2))
    assert rc == 0
    err = capsys.readouterr().err
    assert "events" in err.lower()


@pytest.mark.unit
async def test_export_progress_json_alerts_branch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON alerts progress branch fires after every ``_PROGRESS_EVERY`` rows."""
    monkeypatch.setattr(export_cmd, "_PROGRESS_EVERY", 1)
    monkeypatch.setattr(export_cmd, "_is_tty", lambda: True)
    storage = _FakeStorage(alerts=[_alert(0)])
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(export_type="alerts", limit=1))
    assert rc == 0
    err = capsys.readouterr().err
    assert "alerts" in err.lower()


@pytest.mark.unit
async def test_export_progress_csv_alerts_branch(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSV alerts progress branch fires after every ``_PROGRESS_EVERY`` rows."""
    monkeypatch.setattr(export_cmd, "_PROGRESS_EVERY", 1)
    monkeypatch.setattr(export_cmd, "_is_tty", lambda: True)
    storage = _FakeStorage(alerts=[_alert(0)])
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(
            _args(export_type="alerts", format="csv", limit=1),
        )
    assert rc == 0
    err = capsys.readouterr().err
    assert "alerts" in err.lower()


@pytest.mark.unit
async def test_export_open_output_permission_error_returns_2(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OSError`` raised by ``_open_output`` (e.g. permission denied) → exit 2."""
    storage = _FakeStorage()

    def raise_oserror(_path: str | None) -> tuple[object, bool]:
        msg = "permission denied"
        raise PermissionError(msg)

    with (
        patch.object(export_cmd, "_connect_storage_from_args") as conn,
        patch.object(export_cmd, "_open_output", raise_oserror),
    ):
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(output="/root/out.json"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "permission" in err.lower() or "Error" in err


@pytest.mark.unit
async def test_export_events_total_cap_stops_iteration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``args.limit = 1`` stops the iterator after one row even on a full page."""
    events = [_event(i) for i in range(5)]
    storage = _FakeStorage(events=events)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(limit=1))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


@pytest.mark.unit
async def test_export_alerts_total_cap_stops_iteration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``args.limit = 1`` stops the alert iterator after one row."""
    alerts = [_alert(i) for i in range(5)]
    storage = _FakeStorage(alerts=alerts)
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args(export_type="alerts", limit=1))
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1


@pytest.mark.unit
async def test_export_storage_closed_on_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    storage = _FakeStorage()

    async def boom(_query: Any) -> Any:
        raise RuntimeError("storage exploded")

    storage.query_events = boom  # type: ignore[method-assign]
    with patch.object(export_cmd, "_connect_storage_from_args") as conn:
        conn.return_value = storage
        rc = await export_cmd.run_export(_args())
    assert rc == 1
    assert storage.closed is True
