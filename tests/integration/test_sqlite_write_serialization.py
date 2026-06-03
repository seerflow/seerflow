"""S-340 regression guard: concurrent SQLite writes must not corrupt each other.

Root cause of the residual LANL determinism flake (FP flips 9↔10): every
SQLite write — event batches (``WriteBuffer._periodic_flush`` →
``_write_batch``) and alerts (``write_alert``) — runs on the **same**
``aiosqlite.Connection`` under one implicit transaction with no
connection-level serialization. When the periodic-flush ``commit()`` interleaves
between an alert's ``INSERT`` and its own ``commit()``, SQLite raises
``cannot commit transaction - SQL statements in progress``; the rollback
discards the uncommitted alert (silently swallowed by the handler) → one alert
vanishes → exactly one false positive disappears.

This test exercises that localized condition directly (a real event flush
concurrent with a real ``write_alert`` via ``asyncio.gather``) so it FAILS
pre-fix (``persisted`` < ``attempted`` / ``OperationalError``) and PASSES once
all write transactions are serialized behind a connection-level lock — without
relying on CI scheduling luck.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path

_ATTEMPTS = 8
_EVENTS_PER_FLUSH = 50


def _make_alert(i: int) -> Alert:
    return Alert(
        alert_id=f"alert-{i}",
        alert_type="correlation",
        timestamp_ns=1_000 + i,
        severity_id=SeverityLevel.ERROR,
        rule_name="c2-beaconing",
        description="serialization regression",
        entity_uuid=f"entity-{i}",
        entity_value=f"10.0.0.{i}",
        entity_type="ip",
        contributing_events=(),
        dedup_key=f"dedup-{i}",
        dedup_count=1,
        risk_score=0.5,
    )


def _make_event(seq: int) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=seq,
        observed_ns=seq,
        message="m",
        source_type="syslog",
        source_id=f"src-{seq}",
    )


async def test_concurrent_event_flush_and_write_alert_persists_all(tmp_path: Path) -> None:
    """A periodic-flush event commit racing a write_alert must not drop the alert.

    Pre-fix: the two commits share one connection's transaction; the event
    flush's commit aborts the alert's transaction and the alert is lost
    (``persisted`` < ``_ATTEMPTS``, or an ``OperationalError`` propagates).
    Post-fix: the connection-level write lock serializes them, so every alert
    is durably persisted.
    """
    config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "race.db"))
    backend = await SqliteBackend.connect(config)
    write_buffer = backend._write_buffer
    assert write_buffer is not None
    # Drive the periodic flush deterministically: cancel the timer task and fire
    # the event commit ourselves concurrently with each alert write.
    assert write_buffer._task is not None
    write_buffer._task.cancel()

    try:
        for i in range(_ATTEMPTS):
            # Buffer a non-trivial event batch so the flush's executemany+commit
            # spans long enough to overlap the concurrent alert write.
            base = i * 1_000
            await backend.write_events([_make_event(base + j) for j in range(_EVENTS_PER_FLUSH)])
            # Run the event flush and the alert write concurrently on the shared
            # connection — the exact pipeline interleave that races on CI.
            flush_task = asyncio.create_task(write_buffer.flush())
            alert_task = asyncio.create_task(backend.write_alert(_make_alert(i)))
            results = await asyncio.gather(flush_task, alert_task, return_exceptions=True)
            for r in results:
                assert not isinstance(r, BaseException), f"write raised under contention: {r!r}"

        await backend.flush()
        page = await backend.query_alerts(AlertQuery(limit=1_000))
        assert len(page.items) == _ATTEMPTS, (
            f"expected {_ATTEMPTS} alerts persisted, got {len(page.items)} — "
            "a concurrent event-flush commit clobbered an alert write transaction"
        )
    finally:
        await backend.close()
