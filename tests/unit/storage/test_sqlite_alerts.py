"""Unit tests for SqliteAlertMixin feedback-event methods (S-066)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def sqlite_storage(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    """A fresh SqliteBackend per test."""
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


def make_alert(*, alert_id: str = "a-1", feedback: str = "") -> Alert:
    eid = str(uuid.uuid4())
    return Alert(
        alert_id=alert_id,
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="test-rule",
        description="t",
        entity_uuid=eid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"hst:1:syslog:{alert_id}",
        feedback=feedback,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_append_feedback_event_persists_row(sqlite_storage: SqliteBackend) -> None:
    await sqlite_storage.append_feedback_event(
        alert_id="a-1",
        feedback="tp",
        note="looks real",
        origin="dashboard",
        submitted_at_ns=1_700_000_000_000_000_000,
    )
    page = await sqlite_storage.list_feedback_events("a-1")
    assert page.total == 1
    (ev,) = page.items
    assert ev.feedback == "tp"
    assert ev.origin == "dashboard"
    assert ev.note == "looks real"
    assert ev.submitted_at_ns == 1_700_000_000_000_000_000


@pytest.mark.asyncio
async def test_list_feedback_events_newest_first(sqlite_storage: SqliteBackend) -> None:
    for ts in (10, 20, 30):
        await sqlite_storage.append_feedback_event(
            alert_id="a-1",
            feedback="tp" if ts != 20 else "fp",
            note="",
            origin="dashboard",
            submitted_at_ns=ts,
        )
    page = await sqlite_storage.list_feedback_events("a-1")
    assert [e.submitted_at_ns for e in page.items] == [30, 20, 10]
    assert page.total == 3


@pytest.mark.asyncio
async def test_list_feedback_events_pagination(sqlite_storage: SqliteBackend) -> None:
    for ts in range(1, 6):
        await sqlite_storage.append_feedback_event("a-1", "tp", "", "cli", ts)
    page2 = await sqlite_storage.list_feedback_events("a-1", page=2, limit=2)
    assert [e.submitted_at_ns for e in page2.items] == [3, 2]
    assert page2.total == 5
    assert page2.page == 2
    assert page2.limit == 2


@pytest.mark.asyncio
async def test_list_feedback_events_unknown_alert_empty(
    sqlite_storage: SqliteBackend,
) -> None:
    page = await sqlite_storage.list_feedback_events("missing")
    assert page.total == 0
    assert page.items == ()


@pytest.mark.asyncio
async def test_update_feedback_also_appends_log_row(sqlite_storage: SqliteBackend) -> None:
    alert = make_alert(alert_id="a-1", feedback="")
    await sqlite_storage.write_alert(alert)
    await sqlite_storage.update_feedback("a-1", "fp", note="too noisy", origin="dashboard")
    page = await sqlite_storage.list_feedback_events("a-1")
    assert page.total == 1
    (ev,) = page.items
    assert ev.feedback == "fp"
    assert ev.origin == "dashboard"
    assert ev.note == "too noisy"


@pytest.mark.asyncio
async def test_list_feedback_events_includes_monotonic_id(
    sqlite_storage: SqliteBackend,
) -> None:
    """Rows carry a positive, monotonically-increasing autoincrement ``id``."""
    for ts in (10, 20, 30):
        await sqlite_storage.append_feedback_event("a-1", "tp", "", "dashboard", ts)
    page = await sqlite_storage.list_feedback_events("a-1")
    assert all(ev.id > 0 for ev in page.items)
    # newest-first, so ids should be strictly decreasing
    ids = [ev.id for ev in page.items]
    assert ids == sorted(ids, reverse=True)
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_update_feedback_rolls_back_on_insert_failure(
    sqlite_storage: SqliteBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insert failure must roll back the alert UPDATE — no half-written state."""
    alert = make_alert(alert_id="a-1", feedback="")
    await sqlite_storage.write_alert(alert)

    real_execute = sqlite_storage._conn.execute

    async def failing_execute(sql: str, *args: object, **kwargs: object) -> object:
        if isinstance(sql, str) and sql.startswith("INSERT INTO alert_feedback_events"):
            raise RuntimeError("boom")
        return await real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(sqlite_storage._conn, "execute", failing_execute)

    with pytest.raises(RuntimeError, match="boom"):
        await sqlite_storage.update_feedback("a-1", "tp", "", origin="dashboard")

    monkeypatch.setattr(sqlite_storage._conn, "execute", real_execute)
    stored = await sqlite_storage.get_alert_by_id("a-1")
    assert stored is not None
    assert stored.feedback == ""
    page = await sqlite_storage.list_feedback_events("a-1")
    assert page.total == 0


@pytest.mark.asyncio
async def test_update_feedback_missing_alert_does_not_write_log(
    sqlite_storage: SqliteBackend,
) -> None:
    """Missing alert is a silent no-op; no audit-log row is written."""
    await sqlite_storage.update_feedback("does-not-exist", "tp", "", origin="api")
    page = await sqlite_storage.list_feedback_events("does-not-exist")
    assert page.total == 0
    assert page.items == ()
