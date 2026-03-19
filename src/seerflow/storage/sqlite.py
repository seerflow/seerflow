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
import logging
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import msgspec

from seerflow.config import ConfigError, StorageConfig
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import EventQuery, Page

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


def _validate_path(path: str) -> None:
    """Reject paths containing null bytes."""
    if "\x00" in path:
        msg = f"Path contains null byte: {path!r}"
        raise ConfigError(msg)


# ---------------------------------------------------------------------------
# FTS5 input sanitisation
# ---------------------------------------------------------------------------

_MAX_FTS_QUERY_LENGTH = 256


def _sanitize_fts_query(query: str) -> str:
    """Convert user input to a safe FTS5 phrase query.

    Strips double quotes, removes control characters, caps length at 256,
    and wraps in phrase quotes to prevent FTS5 operator injection.
    """
    cleaned = "".join(c for c in query if c.isprintable())
    cleaned = cleaned.replace('"', "")
    cleaned = cleaned[:_MAX_FTS_QUERY_LENGTH]
    cleaned = cleaned.strip()
    if not cleaned:
        return '""'
    return f'"{cleaned}"'


# ---------------------------------------------------------------------------
# Dynamic SQL builder
# ---------------------------------------------------------------------------


def _build_query(filters: EventQuery) -> tuple[str, str, list[Any]]:
    """Build WHERE clause, JOIN clause, and params from EventQuery."""
    clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []

    if filters.time_range is not None:
        clauses.append("e.timestamp_ns >= ?")
        params.append(filters.time_range.start_ns)
        clauses.append("e.timestamp_ns <= ?")
        params.append(filters.time_range.end_ns)

    if filters.source_type is not None:
        clauses.append("e.source_type = ?")
        params.append(filters.source_type)

    if filters.severity_min is not None:
        clauses.append("e.severity_id >= ?")
        params.append(filters.severity_min)

    if filters.template_id is not None:
        clauses.append("e.template_id = ?")
        params.append(filters.template_id)

    if filters.entity_uuid is not None:
        joins.append("JOIN entity_events ee ON ee.event_id = e.event_id")
        clauses.append("ee.entity_uuid = ?")
        params.append(filters.entity_uuid)

    if filters.text_query is not None:
        safe_query = _sanitize_fts_query(filters.text_query)
        joins.append("JOIN events_fts fts ON fts.rowid = e.rowid")
        clauses.append("fts.events_fts MATCH ?")
        params.append(safe_query)

    where = " AND ".join(clauses) if clauses else "1=1"
    join_str = " ".join(joins)
    return where, join_str, params


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
    "PRAGMA journal_mode=WAL",  # concurrent reads during writes
    "PRAGMA synchronous=NORMAL",  # fsync on checkpoint only — ~100ms loss on power fail
    "PRAGMA cache_size=-64000",  # 64 MiB in-memory page cache
    "PRAGMA mmap_size=268435456",  # 256 MiB memory-mapped I/O (fallback to normal I/O)
    "PRAGMA temp_store=MEMORY",  # temp tables in RAM
    "PRAGMA busy_timeout=5000",  # 5 s retry on locked DB
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
    """Create all tables, indexes, and triggers (idempotent).

    WARNING: Uses ``executescript`` which auto-commits any open transaction.
    Must only be called on a freshly opened connection with no pending writes.
    """
    await conn.executescript(_SCHEMA_DDL)


class WriteBuffer:
    """Async event buffer with size-threshold and periodic flush.

    The lock protects only the buffer drain — the flush callback runs
    outside the lock so ``append()`` is never blocked by a DB write.

    NOTE: ``append()`` assumes a single writer coroutine. If multiple
    coroutines call ``append()`` concurrently, the buffer may briefly
    exceed ``max_size`` before flushing. This is safe but not optimal.
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
        if self._task is not None:
            return
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
            try:
                await self.flush()
            except Exception:
                _log.exception("WriteBuffer: periodic flush failed")


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
            parent_dir = Path(path).parent
            _validate_path(str(parent_dir))
            parent_dir.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(path)
        try:
            for pragma in _PRAGMAS:
                await conn.execute(pragma)
            await _init_schema(conn)
        except Exception:
            await conn.close()
            raise

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
        """Query events with composable filters and pagination."""
        where, join_str, params = _build_query(filters)

        # Count query
        count_sql = f"SELECT COUNT(*) FROM events e {join_str} WHERE {where}"  # noqa: S608
        cursor = await self._conn.execute(count_sql, params)
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # Data query
        offset = (filters.page - 1) * filters.limit
        data_sql = (
            f"SELECT e.data FROM events e {join_str} "  # noqa: S608
            f"WHERE {where} ORDER BY e.timestamp_ns DESC LIMIT ? OFFSET ?"
        )
        cursor = await self._conn.execute(data_sql, [*params, filters.limit, offset])
        rows = await cursor.fetchall()

        items = tuple(
            msgspec.msgpack.decode(row[0], type=SeerflowEvent)
            for row in rows
        )
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]:
        """Full-text search using FTS5 phrase matching."""
        safe_query = _sanitize_fts_query(query)
        if safe_query == '""':
            return []

        sql = (
            "SELECT e.data FROM events e "
            "JOIN events_fts fts ON fts.rowid = e.rowid "
            "WHERE fts.events_fts MATCH ? "
            "ORDER BY e.timestamp_ns DESC LIMIT ?"
        )
        cursor = await self._conn.execute(sql, [safe_query, limit])
        rows = await cursor.fetchall()
        return [
            msgspec.msgpack.decode(row[0], type=SeerflowEvent)
            for row in rows
        ]

    async def _write_batch(self, events: list[SeerflowEvent]) -> None:
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
                    event.template_id if event.template_id != -1 else None,
                    event.message,
                    json.dumps(list(event.entity_refs)),
                    data,
                )
            )
            entity_rows.extend(
                (entity_uuid, event_id_str, event.timestamp_ns)
                for entity_uuid in event.entity_refs
            )
        try:
            await self._conn.executemany(_INSERT_EVENT_SQL, event_rows)
            if entity_rows:
                await self._conn.executemany(_INSERT_ENTITY_EVENT_SQL, entity_rows)
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("SQLite batch write failed — %d events lost", len(events))
            raise
