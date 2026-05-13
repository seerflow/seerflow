"""PostgreSQL storage backend — asyncpg pool, schema, batched writes.

Implements every storage Protocol the SQLite backend covers
(``LogStore``, ``AlertStore``, ``ModelStore``, ``EntityStore``,
``GraphStore`` plus the ``SigmaRuleStateStore`` mixin). All connection
acquisition goes through an :class:`asyncpg.Pool`; concurrent reads are
isolated from the write hot path by acquiring separate connections from
the pool.

Module structure mirrors the SQLite split (S-170 / S-073):

- ``PostgresBackend`` (this file) — pool lifecycle, schema bootstrap,
  events + entity_events + templates, query / FTS, model state, graph
  edges, entity timeline.
- ``_postgres_alerts._PostgresAlertMixin`` — alerts + dedup + feedback
  + MITRE junctions + bucketed counts.
- ``_postgres_sigma_state._PostgresSigmaStateMixin`` — per-rule Sigma
  enabled flag + match counters.

``connect_storage`` (in ``storage.factory``) wraps the import of this
module in a ``try/except ImportError`` so projects that do not install
the ``postgres`` extra never have to import asyncpg.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any

import msgspec

from seerflow.config import ConfigError, StorageConfig
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import EventQuery, Page, TimeRange
from seerflow.storage._postgres_alerts import _PostgresAlertMixin
from seerflow.storage._postgres_sigma_state import _PostgresSigmaStateMixin
from seerflow.storage.sqlite import (
    _MAX_FTS_QUERY_LENGTH,
    _MAX_SEARCH_LIMIT,
    TemplateInfo,
    WriteBuffer,
    _validate_state_key,
    get_related_from_graph,
)

__all__ = ["PostgresBackend"]

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    import asyncpg

    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.models.query import EntityRelation


# ---------------------------------------------------------------------------
# FTS sanitisation — mirrors the SQLite path
# ---------------------------------------------------------------------------


def _parse_delete_status(status: str) -> int:
    """Extract the affected-row count from an asyncpg DELETE status string.

    asyncpg returns strings like ``"DELETE 4"`` from ``conn.execute()``.
    Returns ``0`` when the status cannot be parsed (defensive — should
    never happen for a well-formed DELETE).
    """
    parts = status.split()
    if len(parts) >= 2 and parts[0] == "DELETE":
        try:
            return int(parts[1])
        except ValueError:  # pragma: no cover — defensive
            return 0
    return 0  # pragma: no cover — defensive


def _sanitize_pg_fts_query(query: str) -> str:
    """Sanitise a user-supplied FTS string before handing it to ``plainto_tsquery``.

    Mirrors :func:`seerflow.storage.sqlite._sanitize_fts_query` but returns
    the cleaned plain-text string (no FTS5 phrase wrapping — ``plainto_tsquery``
    treats its argument as a phrase already, ignoring any operator
    metacharacters). Returns ``""`` for an effectively-empty query so the
    caller can short-circuit before issuing the query.
    """
    cleaned = "".join(c for c in query if c.isprintable())
    cleaned = cleaned.replace('"', "").replace("'", "")
    cleaned = cleaned.strip()
    return cleaned[:_MAX_FTS_QUERY_LENGTH]


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    timestamp_ns BIGINT NOT NULL,
    observed_ns  BIGINT NOT NULL,
    severity_id  INTEGER NOT NULL,
    source_type  TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    template_id  INTEGER,
    message      TEXT NOT NULL,
    entity_refs  TEXT,
    data         BYTEA,
    message_fts  tsvector
);
CREATE INDEX IF NOT EXISTS idx_events_time ON events (timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_events_source_sev ON events (source_type, severity_id);
CREATE INDEX IF NOT EXISTS idx_events_template ON events (template_id);
CREATE INDEX IF NOT EXISTS idx_events_message_fts ON events USING GIN (message_fts);

CREATE TABLE IF NOT EXISTS entity_events (
    entity_uuid  TEXT NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    event_id     TEXT NOT NULL,
    PRIMARY KEY (entity_uuid, timestamp_ns, event_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT PRIMARY KEY,
    alert_type   TEXT NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    severity_id  INTEGER NOT NULL,
    rule_name    TEXT NOT NULL,
    entity_uuid  TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    dedup_key    TEXT NOT NULL,
    dedup_count  INTEGER NOT NULL DEFAULT 1,
    risk_score   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    feedback     TEXT,
    data         BYTEA
);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts (timestamp_ns);
CREATE INDEX IF NOT EXISTS idx_alerts_entity ON alerts (entity_uuid);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts (dedup_key);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts (alert_type);

CREATE TABLE IF NOT EXISTS model_state (
    key        TEXT PRIMARY KEY,
    data       BYTEA NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    template_id     INTEGER PRIMARY KEY,
    template_str    TEXT NOT NULL,
    first_seen_ns   BIGINT NOT NULL,
    last_seen_ns    BIGINT NOT NULL,
    event_count     INTEGER NOT NULL DEFAULT 1,
    example_message TEXT
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    rel_type    TEXT NOT NULL,
    first_seen  BIGINT NOT NULL,
    last_seen   BIGINT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (source_id, target_id, rel_type)
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id);

CREATE TABLE IF NOT EXISTS alert_tactics (
    dedup_key    TEXT NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,
    tactic       TEXT NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    PRIMARY KEY (dedup_key, tactic)
);
CREATE INDEX IF NOT EXISTS idx_alert_tactics_tactic_time
    ON alert_tactics(tactic, timestamp_ns DESC);

CREATE TABLE IF NOT EXISTS alert_techniques (
    dedup_key    TEXT NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,
    technique    TEXT NOT NULL,
    timestamp_ns BIGINT NOT NULL,
    PRIMARY KEY (dedup_key, technique)
);
CREATE INDEX IF NOT EXISTS idx_alert_techniques_technique_time
    ON alert_techniques(technique, timestamp_ns DESC);

CREATE TABLE IF NOT EXISTS alert_feedback_events (
    id              BIGSERIAL PRIMARY KEY,
    alert_id        TEXT    NOT NULL,
    feedback        TEXT    NOT NULL CHECK (feedback IN ('tp','fp')),
    note            TEXT    NOT NULL DEFAULT '',
    origin          TEXT    NOT NULL CHECK (origin IN ('dashboard','cli','api')),
    submitted_at_ns BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_alert_time
    ON alert_feedback_events(alert_id, submitted_at_ns DESC);

CREATE TABLE IF NOT EXISTS sigma_rule_state (
    rule_id              TEXT    PRIMARY KEY,
    enabled              INTEGER NOT NULL DEFAULT 1,
    match_count_lifetime BIGINT  NOT NULL DEFAULT 0,
    last_fired_ns        BIGINT,
    updated_at_ns        BIGINT  NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sigma_rule_state_enabled ON sigma_rule_state(enabled);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Maintain ``events.message_fts`` automatically.
CREATE OR REPLACE FUNCTION events_fts_trigger() RETURNS TRIGGER AS $$
BEGIN
    NEW.message_fts := to_tsvector('english', COALESCE(NEW.message, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS events_fts_update ON events;
CREATE TRIGGER events_fts_update
    BEFORE INSERT OR UPDATE OF message ON events
    FOR EACH ROW EXECUTE FUNCTION events_fts_trigger();
"""


_INSERT_EVENT_SQL = """
INSERT INTO events (
    event_id, timestamp_ns, observed_ns, severity_id,
    source_type, source_id, template_id, message,
    entity_refs, data
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (event_id) DO NOTHING
"""

_INSERT_ENTITY_EVENT_SQL = """
INSERT INTO entity_events (entity_uuid, event_id, timestamp_ns)
VALUES ($1, $2, $3)
ON CONFLICT (entity_uuid, timestamp_ns, event_id) DO NOTHING
"""

_SAVE_STATE_SQL = """
INSERT INTO model_state (key, data, updated_at)
VALUES ($1, $2, $3)
ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at
"""
_LOAD_STATE_SQL = "SELECT data FROM model_state WHERE key = $1"
_DELETE_STATE_SQL = "DELETE FROM model_state WHERE key = $1"

_UPSERT_EDGE_SQL = """
INSERT INTO graph_edges (source_id, target_id, rel_type, first_seen, last_seen, event_count)
VALUES ($1, $2, $3, $4, $4, 1)
ON CONFLICT (source_id, target_id, rel_type) DO UPDATE SET
    first_seen = LEAST(graph_edges.first_seen, EXCLUDED.first_seen),
    last_seen = GREATEST(graph_edges.last_seen, EXCLUDED.last_seen),
    event_count = graph_edges.event_count + 1
"""

# Template upsert — mirrors ``_UPSERT_TEMPLATE_SQL`` in the SQLite path.
# ``first_seen_ns`` and ``example_message`` are deliberately not overwritten so
# the original discovery metadata is preserved.
_UPSERT_TEMPLATE_SQL = """
INSERT INTO templates (
    template_id, template_str, first_seen_ns,
    last_seen_ns, event_count, example_message
) VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (template_id) DO UPDATE SET
    last_seen_ns = GREATEST(templates.last_seen_ns, EXCLUDED.last_seen_ns),
    event_count = templates.event_count + EXCLUDED.event_count,
    template_str = EXCLUDED.template_str
"""


# ---------------------------------------------------------------------------
# Dynamic SQL builder
# ---------------------------------------------------------------------------


def _build_pg_query(filters: EventQuery, start_param: int = 1) -> tuple[str, str, list[Any], int]:
    """Build WHERE clause, JOIN clause, params, and the next free placeholder index.

    Mirrors :func:`seerflow.storage.sqlite._build_query` but emits asyncpg-
    style ``$N`` placeholders. The returned ``next_param`` value lets the
    caller append LIMIT / OFFSET bindings without recounting.
    """
    clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []
    n = start_param

    def add(clause_tmpl: str, value: Any) -> None:
        nonlocal n
        clauses.append(clause_tmpl.format(n=n))
        params.append(value)
        n += 1

    if filters.time_range is not None:
        add("e.timestamp_ns >= ${n}", filters.time_range.start_ns)
        add("e.timestamp_ns <= ${n}", filters.time_range.end_ns)
    if filters.source_type is not None:
        add("e.source_type = ${n}", filters.source_type)
    if filters.severity_min is not None:
        add("e.severity_id >= ${n}", filters.severity_min)
    if filters.template_id is not None:
        add("e.template_id = ${n}", filters.template_id)
    if filters.entity_uuid is not None:
        joins.append("JOIN entity_events ee ON ee.event_id = e.event_id")
        add("ee.entity_uuid = ${n}", filters.entity_uuid)
    if filters.text_query is not None:
        cleaned = _sanitize_pg_fts_query(filters.text_query)
        if cleaned:
            clauses.append(f"e.message_fts @@ plainto_tsquery('english', ${n})")
            params.append(cleaned)
            n += 1
        else:
            # Empty cleaned query — match nothing, mirroring SQLite's empty
            # phrase behaviour.
            clauses.append("1=0")

    where = " AND ".join(clauses) if clauses else "TRUE"
    join_str = " ".join(joins)
    return where, join_str, params, n


# ---------------------------------------------------------------------------
# PostgresBackend
# ---------------------------------------------------------------------------


_MISSING_ASYNCPG_MSG = (
    "PostgreSQL backend requires the 'postgres' extra. Install with: uv sync --extra postgres"
)


class PostgresBackend(_PostgresAlertMixin, _PostgresSigmaStateMixin):
    """Async PostgreSQL backend backed by an asyncpg connection pool."""

    __slots__ = ("_closed", "_config", "_entity_graph", "_pool", "_write_buffer")

    def __init__(self, pool: asyncpg.Pool, config: StorageConfig) -> None:
        self._pool = pool
        self._config = config
        self._write_buffer: WriteBuffer | None = None
        self._closed = False
        self._entity_graph: EntityGraph | None = None

    @classmethod
    async def connect(cls, config: StorageConfig) -> PostgresBackend:
        """Open an asyncpg pool, bootstrap the schema, run pending migrations.

        Raises:
            ConfigError: When the ``postgres`` extra is not installed
                (asyncpg import fails) or the configured ``postgresql_url``
                is empty.
        """
        dsn = config.postgresql_url
        if not dsn:
            raise ConfigError("storage.postgresql_url is required when backend='postgresql'")

        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover — exercised by factory test
            raise ConfigError(_MISSING_ASYNCPG_MSG) from exc

        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=config.postgresql_pool_min_size,
            max_size=config.postgresql_pool_max_size,
            command_timeout=config.postgresql_command_timeout_s,
            statement_cache_size=512,
        )
        if pool is None:  # pragma: no cover — asyncpg returns None on misconfigured DSNs
            raise ConfigError("asyncpg.create_pool returned None — invalid postgresql_url")

        try:
            async with pool.acquire() as conn:
                await _init_schema(conn)
                from seerflow.storage.postgres_migrations import (
                    run_pg_migrations,
                )

                applied = await run_pg_migrations(conn)
                if applied > 0:
                    _log.info("Applied %d Postgres schema migration(s)", applied)
        except Exception:
            await pool.close()
            raise

        backend = cls(pool, config)
        backend._write_buffer = WriteBuffer(backend._write_batch)
        backend._write_buffer.start()
        return backend

    async def close(self) -> None:
        """Flush pending writes and close the connection pool (idempotent)."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._write_buffer is not None:
                await self._write_buffer.close()
        finally:
            await self._pool.close()

    async def flush(self) -> None:
        """Flush pending writes to PostgreSQL."""
        if self._closed or self._write_buffer is None:
            return
        await self._write_buffer.flush()

    # ------------------------------------------------------------------
    # LogStore — events
    # ------------------------------------------------------------------

    async def write_events(self, events: list[SeerflowEvent]) -> None:
        """Buffer events for batched writing to PostgreSQL."""
        if not events:
            return
        if self._write_buffer is not None:
            await self._write_buffer.append(events)

    async def _write_batch(self, events: list[SeerflowEvent]) -> None:
        """Serialize and persist a batch of events to PostgreSQL."""
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

        async with self._pool.acquire() as conn, conn.transaction():
            try:
                await conn.executemany(_INSERT_EVENT_SQL, event_rows)
                if entity_rows:
                    await conn.executemany(_INSERT_ENTITY_EVENT_SQL, entity_rows)
            except Exception:
                _log.exception(
                    "Postgres batch write failed — %d events not committed", len(events)
                )
                raise

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
        """Query events with composable filters and pagination."""
        where, join_str, params, next_n = _build_pg_query(filters)

        count_sql = f"SELECT COUNT(*) FROM events e {join_str} WHERE {where}"  # noqa: S608  # nosec B608
        offset = (filters.page - 1) * filters.limit
        data_sql = (
            f"SELECT e.data FROM events e {join_str} "  # noqa: S608  # nosec B608
            f"WHERE {where} ORDER BY e.timestamp_ns DESC "
            f"LIMIT ${next_n} OFFSET ${next_n + 1}"
        )
        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(count_sql, *params)
            total = int(total_row[0]) if total_row else 0
            rows = await conn.fetch(data_sql, *params, filters.limit, offset)

        items = tuple(msgspec.msgpack.decode(row["data"], type=SeerflowEvent) for row in rows)
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]:
        """Full-text search using PostgreSQL ``tsvector`` matching."""
        cleaned = _sanitize_pg_fts_query(query)
        if not cleaned:
            return []
        clamped_limit = min(max(limit, 1), _MAX_SEARCH_LIMIT)
        sql = (
            "SELECT data FROM events "
            "WHERE message_fts @@ plainto_tsquery('english', $1) "
            "ORDER BY timestamp_ns DESC LIMIT $2"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, cleaned, clamped_limit)
        return [msgspec.msgpack.decode(row["data"], type=SeerflowEvent) for row in rows]

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

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
        async with self._pool.acquire() as conn:
            await conn.executemany(_UPSERT_TEMPLATE_SQL, rows)

    async def get_templates(self, limit: int = 1000) -> list[TemplateInfo]:
        """Query templates sorted by event_count descending."""
        clamped = min(max(limit, 1), 10000)
        sql = (
            "SELECT template_id, template_str, first_seen_ns, last_seen_ns, "
            "event_count, example_message FROM templates "
            "ORDER BY event_count DESC LIMIT $1"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, clamped)
        return [
            TemplateInfo(
                template_id=int(row["template_id"]),
                template_str=row["template_str"],
                first_seen_ns=int(row["first_seen_ns"]),
                last_seen_ns=int(row["last_seen_ns"]),
                event_count=int(row["event_count"]),
                example_message=row["example_message"],
            )
            for row in rows
        ]

    async def prune_templates(self, min_count: int) -> int:
        """Delete templates with ``event_count < min_count``. See SQLite impl."""
        if min_count < 0:
            msg = f"min_count must be >= 0, got {min_count!r}"
            raise ValueError(msg)
        if min_count == 0:
            return 0
        async with self._pool.acquire() as conn:
            # asyncpg returns a status string like "DELETE 4". Parse the count.
            status = await conn.execute("DELETE FROM templates WHERE event_count < $1", min_count)
        return _parse_delete_status(status)

    async def reset_templates(self) -> int:
        """Delete every row from the templates table. See SQLite impl."""
        async with self._pool.acquire() as conn:
            status = await conn.execute("DELETE FROM templates")
        return _parse_delete_status(status)

    # ------------------------------------------------------------------
    # EntityStore
    # ------------------------------------------------------------------

    async def get_timeline(
        self,
        entity_uuid: str,
        time_range: TimeRange,
        source_type: str | None = None,
        severity_min: int | None = None,
        limit: int = 10_000,
    ) -> list[SeerflowEvent]:
        clamped_limit = min(max(limit, 1), 10_000)
        clauses = [
            "ee.entity_uuid = $1",
            "e.timestamp_ns >= $2",
            "e.timestamp_ns <= $3",
        ]
        params: list[Any] = [entity_uuid, time_range.start_ns, time_range.end_ns]
        n = 4
        if source_type is not None:
            clauses.append(f"e.source_type = ${n}")
            params.append(source_type)
            n += 1
        if severity_min is not None:
            clauses.append(f"e.severity_id >= ${n}")
            params.append(severity_min)
            n += 1
        where = " AND ".join(clauses)
        sql = (
            f"SELECT e.data FROM events e "  # noqa: S608  # nosec B608
            f"JOIN entity_events ee ON ee.event_id = e.event_id "
            f"WHERE {where} ORDER BY e.timestamp_ns ASC LIMIT ${n}"
        )
        params.append(clamped_limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [msgspec.msgpack.decode(row["data"], type=SeerflowEvent) for row in rows]

    def set_entity_graph(self, graph: EntityGraph) -> None:
        """Set the EntityGraph for relationship queries."""
        self._entity_graph = graph

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        """Get entities related to the given entity via the in-memory graph."""
        if self._entity_graph is None:
            return []
        return get_related_from_graph(self._entity_graph, entity_uuid)

    # ------------------------------------------------------------------
    # ModelStore
    # ------------------------------------------------------------------

    async def save_state(self, key: str, data: bytes) -> None:
        _validate_state_key(key)
        async with self._pool.acquire() as conn:
            await conn.execute(_SAVE_STATE_SQL, key, data, time.time_ns())

    async def load_state(self, key: str) -> bytes | None:
        _validate_state_key(key)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_LOAD_STATE_SQL, key)
        if row is None:
            return None
        value = row["data"]
        return bytes(value) if value is not None else None

    async def delete_state(self, key: str) -> None:
        _validate_state_key(key)
        async with self._pool.acquire() as conn:
            await conn.execute(_DELETE_STATE_SQL, key)

    # ------------------------------------------------------------------
    # GraphStore
    # ------------------------------------------------------------------

    async def write_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_UPSERT_EDGE_SQL, source_id, target_id, rel_type, timestamp_ns)

    async def load_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        sql = (
            "SELECT source_id, target_id, rel_type, first_seen, last_seen, event_count "
            "FROM graph_edges"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [
            (
                row["source_id"],
                row["target_id"],
                row["rel_type"],
                int(row["first_seen"]),
                int(row["last_seen"]),
                int(row["event_count"]),
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


async def _init_schema(conn: asyncpg.Connection) -> None:
    """Create all tables, indexes, and triggers (idempotent)."""
    await conn.execute(_SCHEMA_DDL)


# Re-exports kept for symmetry with ``storage.sqlite`` so importers can use
# either backend interchangeably for housekeeping helpers.
__all__ = ["_INSERT_EVENT_SQL", "PostgresBackend", "_build_pg_query"]


# Silence linters complaining about unused imports — these symbols are
# part of the public surface of the SQLite module that we deliberately
# re-use here.
_ = (asyncio, contextlib)
