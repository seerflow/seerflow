"""SQLite storage backend — schema creation, event writes, and queries.

Implements ``LogStore`` via aiosqlite with WAL mode.
Schema is auto-created on first run. Writes are batched via ``WriteBuffer``
(1000 events or 100ms, whichever first). Queries support composable filters,
pagination, and FTS5 full-text search.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiosqlite
import msgspec

from seerflow.config import ConfigError, StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery, EventQuery, Page, TimeRange
from seerflow.sigma.attack import format_technique

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.models._types import FeedbackType
    from seerflow.models.query import EntityRelation


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
_MAX_SEARCH_LIMIT = 10_000


def _sanitize_fts_query(query: str) -> str:
    """Convert user input to a safe FTS5 phrase query.

    Wraps cleaned input in double quotes, producing an FTS5 phrase literal.
    Inside a phrase, all FTS5 operators (AND, OR, NOT, NEAR, ^, *, parentheses)
    are treated as literal text.

    Steps: remove non-printable chars → strip quotes (single + double) →
    strip whitespace → cap at 256 chars → wrap in phrase quotes.
    """
    cleaned = "".join(c for c in query if c.isprintable())
    cleaned = cleaned.replace('"', "").replace("'", "")
    cleaned = cleaned.strip()
    cleaned = cleaned[:_MAX_FTS_QUERY_LENGTH]
    if not cleaned:
        return '""'
    return f'"{cleaned}"'


# ---------------------------------------------------------------------------
# Template metadata
# ---------------------------------------------------------------------------


class TemplateInfo(msgspec.Struct, frozen=True, gc=False):
    """Template metadata for the templates table."""

    template_id: int
    template_str: str
    first_seen_ns: int
    last_seen_ns: int
    event_count: int
    example_message: str | None = None


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
        # Note: template_id=-1 is stored as NULL in the DB (sentinel conversion
        # in _write_batch). Filtering by -1 will match nothing. Use None to skip.
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

CREATE TABLE IF NOT EXISTS templates (
    template_id    INTEGER PRIMARY KEY,
    template_str   TEXT    NOT NULL,
    first_seen_ns  INTEGER NOT NULL,
    last_seen_ns   INTEGER NOT NULL,
    event_count    INTEGER NOT NULL DEFAULT 1,
    example_message TEXT
);
"""


_PRAGMAS = (
    "PRAGMA page_size=8192",  # 8 KiB pages — must be set before journal_mode on new DBs
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

# first_seen_ns and example_message are intentionally excluded from DO UPDATE SET —
# they preserve the values from the original INSERT (first discovery).
_UPSERT_TEMPLATE_SQL = """\
INSERT INTO templates (
    template_id, template_str, first_seen_ns,
    last_seen_ns, event_count, example_message
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(template_id) DO UPDATE SET
    last_seen_ns = MAX(templates.last_seen_ns, excluded.last_seen_ns),
    event_count = templates.event_count + excluded.event_count,
    template_str = excluded.template_str
"""


# NOTE(S-073): when the PostgreSQL backend lands, mirror this schema and query
# shape. Junction tables carry a denormalized ``timestamp_ns`` so the filter
# path drives from the junction index without a sort step:
#     CREATE TABLE alert_tactics (
#         dedup_key    TEXT    NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,
#         tactic       TEXT    NOT NULL,
#         timestamp_ns BIGINT  NOT NULL,
#         PRIMARY KEY (dedup_key, tactic)
#     );
#     CREATE INDEX idx_alert_tactics_tactic_time
#         ON alert_tactics(tactic, timestamp_ns DESC);
# (same for alert_techniques). The PG ``write_alert`` must dual-write junction
# rows in the same transaction as the alert upsert, keyed on ``dedup_key``.
def _build_alert_query(filters: AlertQuery) -> tuple[str, list[Any]]:
    """Build WHERE clause and params from AlertQuery (including mitre filters).

    When ``tactic`` or ``technique`` is set, the caller drives the query from
    the matching junction table (``alert_tactics at`` or ``alert_techniques
    atq``) so the composite ``(tactic|technique, timestamp_ns DESC)`` index
    satisfies both the predicate and the ORDER BY. When both are set, the
    driver is the tactic junction and technique becomes a correlated EXISTS.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if filters.time_range is not None:
        clauses.append("a.timestamp_ns >= ?")
        params.append(filters.time_range.start_ns)
        clauses.append("a.timestamp_ns <= ?")
        params.append(filters.time_range.end_ns)
    if filters.alert_type is not None:
        clauses.append("a.alert_type = ?")
        params.append(filters.alert_type)
    if filters.severity_min is not None:
        clauses.append("a.severity_id >= ?")
        params.append(filters.severity_min)
    if filters.entity_uuid is not None:
        clauses.append("a.entity_uuid = ?")
        params.append(filters.entity_uuid)
    if filters.tactic is not None:
        clauses.append("at.tactic = ?")
        params.append(filters.tactic)
    if filters.technique is not None:
        # If tactic is also set, the driver is alert_tactics so technique
        # becomes a correlated EXISTS on alert_techniques. Otherwise the
        # driver is alert_techniques and we filter directly on atq.technique.
        if filters.tactic is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM alert_techniques atq2 "
                "WHERE atq2.dedup_key = a.dedup_key AND atq2.technique = ?)"
            )
        else:
            clauses.append("atq.technique = ?")
        params.append(format_technique(filters.technique))
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


_MAX_STATE_KEY_LENGTH = 256


def _validate_state_key(key: str) -> None:
    """Reject keys that violate the ModelStore contract."""
    if not key:
        msg = "model state key must not be empty"
        raise ValueError(msg)
    if len(key) > _MAX_STATE_KEY_LENGTH:
        msg = f"model state key exceeds {_MAX_STATE_KEY_LENGTH} characters: {key!r}"
        raise ValueError(msg)
    if not key.isascii():
        msg = f"model state key must be ASCII-only: {key!r}"
        raise ValueError(msg)


_SAVE_STATE_SQL = "INSERT OR REPLACE INTO model_state (key, data, updated_at) VALUES (?, ?, ?)"
_LOAD_STATE_SQL = "SELECT data FROM model_state WHERE key = ?"

_UPSERT_EDGE_SQL = """\
INSERT INTO graph_edges (source_id, target_id, rel_type, first_seen, last_seen, event_count)
VALUES (?, ?, ?, ?, ?, 1)
ON CONFLICT(source_id, target_id, rel_type) DO UPDATE SET
    first_seen = MIN(first_seen, excluded.first_seen),
    last_seen = MAX(last_seen, excluded.last_seen),
    event_count = event_count + 1"""

_INSERT_ALERT_SQL = """\
INSERT INTO alerts (
    alert_id, alert_type, timestamp_ns, severity_id, rule_name,
    entity_uuid, entity_type, entity_value, dedup_key, dedup_count,
    risk_score, feedback, data
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(dedup_key) DO UPDATE SET
    dedup_count = CASE
        WHEN ABS(excluded.timestamp_ns - alerts.timestamp_ns) <= ?
        THEN alerts.dedup_count + 1
        ELSE 1
    END,
    timestamp_ns = CASE
        WHEN ABS(excluded.timestamp_ns - alerts.timestamp_ns) <= ?
        THEN alerts.timestamp_ns
        ELSE excluded.timestamp_ns
    END,
    alert_id = excluded.alert_id,
    data = excluded.data
RETURNING dedup_count"""


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

    __slots__ = ("_closed", "_conn", "_entity_graph", "_write_buffer")

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_buffer: WriteBuffer | None = None
        self._closed = False
        self._entity_graph: EntityGraph | None = None

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

            from seerflow.storage.migrations import run_migrations

            applied = await run_migrations(conn)
            if applied > 0:
                _log.info("Applied %d schema migration(s)", applied)
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
        try:
            if self._write_buffer is not None:
                await self._write_buffer.close()
        finally:
            await self._conn.close()

    async def flush(self) -> None:
        """Flush pending writes to the database."""
        if self._closed or self._write_buffer is None:
            return
        await self._write_buffer.flush()

    async def write_events(self, events: list[SeerflowEvent]) -> None:
        """Buffer events for batched writing to SQLite."""
        if not events:
            return
        if self._write_buffer is not None:
            await self._write_buffer.append(events)

    async def write_templates(self, templates: list[TemplateInfo]) -> None:
        """Upsert template metadata — increment counts, update last_seen."""
        if not templates:
            return
        rows = [
            (
                t.template_id,
                t.template_str,
                t.first_seen_ns,
                t.last_seen_ns,
                t.event_count,
                t.example_message,
            )
            for t in templates
        ]
        try:
            await self._conn.executemany(_UPSERT_TEMPLATE_SQL, rows)
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("write_templates failed — %d templates not committed", len(rows))
            raise

    async def get_templates(self, limit: int = 1000) -> list[TemplateInfo]:
        """Query templates sorted by event_count descending."""
        clamped = min(max(limit, 1), 10000)
        sql = (
            "SELECT template_id, template_str, first_seen_ns, last_seen_ns,"
            " event_count, example_message FROM templates"
            " ORDER BY event_count DESC LIMIT ?"
        )
        async with await self._conn.execute(sql, [clamped]) as cursor:
            rows = await cursor.fetchall()
        return [TemplateInfo(*row) for row in rows]

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
        """Query events with composable filters and pagination."""
        where, join_str, params = _build_query(filters)

        # join_str and where are assembled from hardcoded SQL fragments in _build_query().
        # User values are bound exclusively via params. No user data is interpolated.
        count_sql = f"SELECT COUNT(*) FROM events e {join_str} WHERE {where}"  # noqa: S608  # nosec B608
        async with await self._conn.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        # Data query
        offset = (filters.page - 1) * filters.limit
        # join_str and where are assembled from hardcoded SQL fragments in _build_query().
        # User values are bound exclusively via params. No user data is interpolated.
        data_sql = (
            f"SELECT e.data FROM events e {join_str} "  # noqa: S608  # nosec B608
            f"WHERE {where} ORDER BY e.timestamp_ns DESC LIMIT ? OFFSET ?"
        )
        async with await self._conn.execute(data_sql, [*params, filters.limit, offset]) as cursor:
            rows = await cursor.fetchall()

        items = tuple(msgspec.msgpack.decode(row[0], type=SeerflowEvent) for row in rows)
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def get_timeline(
        self,
        entity_uuid: str,
        time_range: TimeRange,
        source_type: str | None = None,
        severity_min: int | None = None,
        limit: int = 10_000,
    ) -> list[SeerflowEvent]:
        """Get all events for an entity within a time range, sorted chronologically.

        Uses the entity_events junction table for efficient lookups via
        composite PK (entity_uuid, timestamp_ns, event_id).
        """
        clamped_limit = min(max(limit, 1), 10_000)
        clauses = [
            "ee.entity_uuid = ?",
            "e.timestamp_ns >= ?",
            "e.timestamp_ns <= ?",
        ]
        params: list[Any] = [entity_uuid, time_range.start_ns, time_range.end_ns]

        if source_type is not None:
            clauses.append("e.source_type = ?")
            params.append(source_type)

        if severity_min is not None:
            clauses.append("e.severity_id >= ?")
            params.append(severity_min)

        where = " AND ".join(clauses)
        # where clause assembled from hardcoded SQL fragments above.
        # All user values are bound via params. No user data is interpolated.
        sql = (
            f"SELECT e.data FROM events e "  # noqa: S608  # nosec B608
            f"JOIN entity_events ee ON ee.event_id = e.event_id "
            f"WHERE {where} ORDER BY e.timestamp_ns ASC LIMIT ?"
        )
        params.append(clamped_limit)

        async with await self._conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [msgspec.msgpack.decode(row[0], type=SeerflowEvent) for row in rows]

    def set_entity_graph(self, graph: EntityGraph) -> None:
        """Set the EntityGraph for relationship queries."""
        self._entity_graph = graph

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        """Get entities related to the given entity via graph edges."""
        if self._entity_graph is None:
            return []
        return get_related_from_graph(self._entity_graph, entity_uuid)

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]:
        """Full-text search using FTS5 phrase matching."""
        safe_query = _sanitize_fts_query(query)
        if safe_query == '""':
            return []

        clamped_limit = min(max(limit, 1), _MAX_SEARCH_LIMIT)

        sql = (
            "SELECT e.data FROM events e "
            "JOIN events_fts fts ON fts.rowid = e.rowid "
            "WHERE fts.events_fts MATCH ? "
            "ORDER BY e.timestamp_ns DESC LIMIT ?"
        )
        async with await self._conn.execute(sql, [safe_query, clamped_limit]) as cursor:
            rows = await cursor.fetchall()
        return [msgspec.msgpack.decode(row[0], type=SeerflowEvent) for row in rows]

    async def write_alert(
        self,
        alert: Alert,
        dedup_window_ns: int = 900_000_000_000,
    ) -> bool:
        """Persist an alert with time-windowed dedup upsert on conflict.

        Within *dedup_window_ns* nanoseconds of the existing alert the
        ``dedup_count`` is incremented and the original ``timestamp_ns`` is
        preserved.  Outside the window the count resets to 1 and the
        timestamp is replaced.

        Returns:
            True if this was a new insert or a window-reset (dedup_count == 1),
            False if the alert was a dedup bump within the window
            (dedup_count > 1).
        """
        data = msgspec.msgpack.encode(alert)
        params = (
            alert.alert_id,
            alert.alert_type,
            alert.timestamp_ns,
            int(alert.severity_id),
            alert.rule_name,
            alert.entity_uuid,
            alert.entity_type,
            alert.entity_value,
            alert.dedup_key,
            alert.dedup_count,
            alert.risk_score,
            alert.feedback,
            data,
            dedup_window_ns,
            dedup_window_ns,
        )
        try:
            async with await self._conn.execute(_INSERT_ALERT_SQL, params) as cursor:
                row = await cursor.fetchone()
            await self._conn.execute(
                "DELETE FROM alert_tactics WHERE dedup_key = ?", (alert.dedup_key,)
            )
            await self._conn.execute(
                "DELETE FROM alert_techniques WHERE dedup_key = ?", (alert.dedup_key,)
            )
            if alert.mitre_tactics:
                await self._conn.executemany(
                    "INSERT OR IGNORE INTO alert_tactics "
                    "(dedup_key, tactic, timestamp_ns) VALUES (?, ?, ?)",
                    [(alert.dedup_key, t, alert.timestamp_ns) for t in alert.mitre_tactics],
                )
            if alert.mitre_techniques:
                await self._conn.executemany(
                    "INSERT OR IGNORE INTO alert_techniques "
                    "(dedup_key, technique, timestamp_ns) VALUES (?, ?, ?)",
                    [
                        (alert.dedup_key, format_technique(t), alert.timestamp_ns)
                        for t in alert.mitre_techniques
                    ],
                )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("write_alert failed for alert %s", alert.alert_id)
            raise
        return row is not None and row[0] == 1

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:
        """Query alerts with composable filters and pagination (all SQL-level).

        When a mitre filter (``tactic`` / ``technique``) is set, the query is
        driven from the matching junction table so the composite
        ``(tactic|technique, timestamp_ns DESC)`` index satisfies both the
        predicate and the ORDER BY without scanning the ``alerts`` table.
        """
        where, params = _build_alert_query(filters)

        if filters.tactic is not None:
            driver = "alert_tactics AS at JOIN alerts a ON a.dedup_key = at.dedup_key"
            order_col = "at.timestamp_ns"
        elif filters.technique is not None:
            driver = "alert_techniques AS atq JOIN alerts a ON a.dedup_key = atq.dedup_key"
            order_col = "atq.timestamp_ns"
        else:
            driver = "alerts a"
            order_col = "a.timestamp_ns"

        # driver, where, order_col are assembled from hardcoded SQL fragments;
        # user values are bound exclusively via params.
        count_sql = f"SELECT COUNT(*) FROM {driver} WHERE {where}"  # noqa: S608  # nosec B608
        async with await self._conn.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        offset = (filters.page - 1) * filters.limit
        data_sql = (
            f"SELECT a.data, a.dedup_count FROM {driver} WHERE {where} "  # noqa: S608  # nosec B608
            f"ORDER BY {order_col} DESC LIMIT ? OFFSET ?"
        )
        async with await self._conn.execute(data_sql, [*params, filters.limit, offset]) as cursor:
            rows = await cursor.fetchall()
        items = tuple(
            msgspec.structs.replace(
                msgspec.msgpack.decode(row[0], type=Alert),
                dedup_count=row[1],
            )
            for row in rows
        )
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def update_feedback(self, alert_id: str, feedback: FeedbackType) -> None:
        """Update alert feedback and re-encode the BLOB.

        Implementation note: this performs a SELECT then UPDATE. On the SQLite
        backend this is safe because a single aiosqlite connection serializes
        all operations. A PostgreSQL backend MUST use SELECT ... FOR UPDATE
        inside a transaction to prevent a concurrent write from being lost.
        """
        async with await self._conn.execute(
            "SELECT data FROM alerts WHERE alert_id = ?", [alert_id]
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return
        alert = msgspec.msgpack.decode(row[0], type=Alert)
        updated = msgspec.structs.replace(alert, feedback=feedback)
        data = msgspec.msgpack.encode(updated)
        try:
            await self._conn.execute(
                "UPDATE alerts SET feedback = ?, data = ? WHERE alert_id = ?",
                [feedback, data, alert_id],
            )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("update_feedback failed for alert %s", alert_id)
            raise

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        """Retrieve a single alert by ID, or None if not found."""
        async with await self._conn.execute(
            "SELECT data FROM alerts WHERE alert_id = ?", [alert_id]
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return msgspec.msgpack.decode(row[0], type=Alert)

    async def get_feedback_stats(self) -> dict[str, int]:
        """Return feedback counts: tp, fp, total."""
        async with await self._conn.execute(
            "SELECT feedback, COUNT(*) FROM alerts"
            " WHERE feedback IN ('tp', 'fp') GROUP BY feedback"
        ) as cursor:
            rows = await cursor.fetchall()
        stats: dict[str, int] = {"tp": 0, "fp": 0, "total": 0}
        for fb_type, count in rows:
            if fb_type in ("tp", "fp"):
                stats[fb_type] = count
                stats["total"] += count
        return stats

    async def count_by_severity(self) -> dict[str, int]:
        """Return alert counts grouped by severity name (lowercase).

        Invalid ``severity_id`` values (outside the ``SeverityLevel`` enum)
        are bucketed under ``"unknown"`` so dirty data cannot crash the
        stats endpoint.
        """
        async with await self._conn.execute(
            "SELECT severity_id, COUNT(*) FROM alerts GROUP BY severity_id"
        ) as cursor:
            rows = await cursor.fetchall()
        counts: dict[str, int] = {}
        for severity_id, count in rows:
            try:
                name = SeverityLevel(int(severity_id)).name.lower()
            except (ValueError, TypeError):
                # ValueError: severity_id outside enum range OR non-numeric text
                # TypeError: severity_id is None (SQLite type affinity edge case)
                name = "unknown"
            counts[name] = counts.get(name, 0) + int(count)
        return counts

    async def save_state(self, key: str, data: bytes) -> None:
        """Persist serialized model state (upsert by key)."""
        _validate_state_key(key)
        updated_at = time.time_ns()
        try:
            await self._conn.execute(_SAVE_STATE_SQL, [key, data, updated_at])
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("save_state failed for key %s", key)
            raise

    async def load_state(self, key: str) -> bytes | None:
        """Load serialized model state, or None if not found."""
        _validate_state_key(key)
        async with await self._conn.execute(_LOAD_STATE_SQL, [key]) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def write_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        """Upsert a graph edge. Updates last_seen and increments event_count on conflict."""
        await self._conn.execute(
            _UPSERT_EDGE_SQL,
            (source_id, target_id, rel_type, timestamp_ns, timestamp_ns),
        )
        await self._conn.commit()

    async def load_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        """Load all graph edges for EntityGraph rebuild on startup."""
        sql = (
            "SELECT source_id, target_id, rel_type,"
            " first_seen, last_seen, event_count"
            " FROM graph_edges"
        )
        async with await self._conn.execute(sql) as cursor:
            rows = await cursor.fetchall()
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]

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
            _log.exception("SQLite batch write failed — %d events not committed", len(events))
            raise


# ---------------------------------------------------------------------------
# Standalone graph query helpers
# ---------------------------------------------------------------------------


def get_related_from_graph(
    graph: EntityGraph,
    entity_uuid: str,
) -> list[EntityRelation]:
    """Get related entities from the in-memory EntityGraph."""
    from seerflow.models.query import EntityRelation

    neighbors = graph.get_neighbors_with_rel(entity_uuid)
    if not neighbors:
        return []

    results: list[EntityRelation] = []
    for neighbor_id, rel_type in neighbors:
        if not rel_type:
            _log.debug("No rel_type for edge %s -> %s", entity_uuid, neighbor_id)
            continue
        results.append(
            EntityRelation(
                entity_uuid=neighbor_id,
                entity_type="",
                entity_value="",
                relation_type=rel_type,
            )
        )
    return results
