"""SQLite storage backend — schema creation and event batch writes.

Implements ``LogStore.write_events`` via aiosqlite with WAL mode.
Schema is auto-created on first run. Events are batched via ``WriteBuffer``
(1000 events or 100ms, whichever first) for high-throughput writes.

See: docs/superpowers/specs/2026-03-18-s006-sqlite-backend-design.md
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import msgspec

from seerflow.config import ConfigError, StorageConfig

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import EventQuery, Page


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _validate_path(path: str) -> None:
    """Reject paths containing null bytes."""
    if "\x00" in path:
        msg = f"Path contains null byte: {path!r}"
        raise ConfigError(msg)


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    timestamp_ns INTEGER NOT NULL,
    observed_ns  INTEGER NOT NULL,
    severity_id  INTEGER NOT NULL,
    source_type  TEXT    NOT NULL,
    source_id    TEXT    NOT NULL,
    template_id  INTEGER,
    message      TEXT    NOT NULL,
    entity_refs  TEXT,
    data         BLOB
);

CREATE INDEX IF NOT EXISTS idx_events_time
    ON events (timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_events_source_sev
    ON events (source_type, severity_id);
CREATE INDEX IF NOT EXISTS idx_events_template
    ON events (template_id);

CREATE TABLE IF NOT EXISTS entity_events (
    entity_uuid  TEXT    NOT NULL,
    timestamp_ns INTEGER NOT NULL,
    event_id     TEXT    NOT NULL,
    PRIMARY KEY (entity_uuid, timestamp_ns, event_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT PRIMARY KEY,
    alert_type   TEXT    NOT NULL,
    timestamp_ns INTEGER NOT NULL,
    severity_id  INTEGER NOT NULL,
    rule_name    TEXT    NOT NULL,
    entity_uuid  TEXT    NOT NULL,
    entity_type  TEXT    NOT NULL,
    entity_value TEXT    NOT NULL,
    dedup_key    TEXT    NOT NULL,
    dedup_count  INTEGER NOT NULL DEFAULT 1,
    risk_score   REAL    NOT NULL DEFAULT 0.0,
    feedback     TEXT,
    data         BLOB
);

CREATE INDEX IF NOT EXISTS idx_alerts_time
    ON alerts (timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_alerts_entity
    ON alerts (entity_uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_dedup
    ON alerts (dedup_key);
CREATE INDEX IF NOT EXISTS idx_alerts_type
    ON alerts (alert_type);

CREATE TABLE IF NOT EXISTS model_state (
    key        TEXT PRIMARY KEY,
    data       BLOB    NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    message,
    content=events,
    content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS events_fts_insert AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, message) VALUES (new.rowid, new.message);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_delete AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, message) VALUES ('delete', old.rowid, old.message);
END;

CREATE TRIGGER IF NOT EXISTS events_fts_update AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, message) VALUES ('delete', old.rowid, old.message);
    INSERT INTO events_fts(rowid, message) VALUES (new.rowid, new.message);
END;
"""


_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA mmap_size=268435456",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA busy_timeout=5000",
)

_INSERT_EVENT_SQL = """\
INSERT OR IGNORE INTO events (
    event_id, timestamp_ns, observed_ns, severity_id,
    source_type, source_id, template_id, message,
    entity_refs, data
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_INSERT_ENTITY_EVENT_SQL = """\
INSERT OR IGNORE INTO entity_events (entity_uuid, event_id, timestamp_ns)
VALUES (?, ?, ?)"""


async def _init_schema(conn: aiosqlite.Connection) -> None:
    """Create all tables, indexes, and triggers (idempotent)."""
    await conn.executescript(_SCHEMA_DDL)


class WriteBuffer:
    """Async event buffer with size-threshold and periodic flush.

    The lock protects only the buffer drain — the flush callback runs
    outside the lock so ``append()`` is never blocked by a DB write.
    """

    __slots__ = (
        "_buffer",
        "_callback",
        "_flush_interval",
        "_lock",
        "_max_size",
        "_task",
    )

    def __init__(
        self,
        flush_callback: Callable[[list[Any]], Awaitable[None]],
        max_size: int = 1000,
        flush_interval: float = 0.1,
    ) -> None:
        self._buffer: deque[Any] = deque()
        self._callback = flush_callback
        self._max_size = max_size
        self._flush_interval = flush_interval
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the periodic flush background task."""
        self._task = asyncio.create_task(self._periodic_flush())

    async def append(self, events: list[Any]) -> None:
        """Add events to the buffer; auto-flush if size threshold is reached."""
        self._buffer.extend(events)
        if len(self._buffer) >= self._max_size:
            await self.flush()

    async def flush(self) -> None:
        """Drain the buffer and invoke the flush callback."""
        async with self._lock:
            if not self._buffer:
                return
            batch = list(self._buffer)
            self._buffer.clear()
        await self._callback(batch)

    async def close(self) -> None:
        """Cancel periodic task (if running) and flush remaining events."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush()

    async def _periodic_flush(self) -> None:
        """Flush on a timer until cancelled."""
        while True:
            await asyncio.sleep(self._flush_interval)
            await self.flush()


# ---------------------------------------------------------------------------
# SqliteBackend
# ---------------------------------------------------------------------------


class SqliteBackend:
    """SQLite storage backend implementing LogStore.write_events."""

    __slots__ = ("_closed", "_conn", "_write_buffer")

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_buffer: WriteBuffer | None = None
        self._closed = False

    @classmethod
    async def connect(cls, config: StorageConfig) -> SqliteBackend:
        """Open an aiosqlite connection, apply PRAGMAs, and create the schema."""
        path = config.sqlite_path
        if path != ":memory:":
            _validate_path(path)
            parent = str(Path(path).parent)
            _validate_path(parent)
            os.makedirs(parent, exist_ok=True)

        conn = await aiosqlite.connect(path)
        for pragma in _PRAGMAS:
            await conn.execute(pragma)
        await _init_schema(conn)

        backend = cls(conn)
        backend._write_buffer = WriteBuffer(backend._write_batch)
        backend._write_buffer.start()
        return backend

    async def close(self) -> None:
        """Flush pending writes and close the connection (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if self._write_buffer is not None:
            await self._write_buffer.close()
        await self._conn.close()

    async def write_events(self, events: list[SeerflowEvent]) -> None:
        """Buffer events for batched writing to SQLite."""
        if not events:
            return
        if self._write_buffer is not None:
            await self._write_buffer.append(events)

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
        """Query stored events (not yet implemented)."""
        raise NotImplementedError("query_events is implemented in S-007")

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]:
        """Full-text search across stored events (not yet implemented)."""
        raise NotImplementedError("search_text is implemented in S-007")

    async def _write_batch(self, events: list[Any]) -> None:
        """Serialize and persist a batch of events to SQLite."""
        if not events:
            return
        event_rows: list[tuple[Any, ...]] = []
        entity_rows: list[tuple[str, str, int]] = []
        for event in events:
            data = msgspec.msgpack.encode(event)
            event_id_str = str(event.event_id)
            event_rows.append(
                (
                    event_id_str,
                    event.timestamp_ns,
                    event.observed_ns,
                    int(event.severity_id),
                    event.source_type,
                    event.source_id,
                    event.template_id,
                    event.message,
                    json.dumps(list(event.entity_refs)),
                    data,
                )
            )
            for entity_uuid in event.entity_refs:
                entity_rows.append((entity_uuid, event_id_str, event.timestamp_ns))
        await self._conn.executemany(_INSERT_EVENT_SQL, event_rows)
        if entity_rows:
            await self._conn.executemany(_INSERT_ENTITY_EVENT_SQL, entity_rows)
        await self._conn.commit()
