"""PostgreSQL schema migration system (S-073).

Mirror of :mod:`seerflow.storage.migrations` for the asyncpg backend. The
main schema DDL is created by :func:`seerflow.storage.postgres._init_schema`
on a freshly opened pool connection; this module owns the post-bootstrap
``schema_version`` ledger and any later schema deltas.

Migration version numbers match the SQLite list (1-6) for parity. v1
is a bootstrap no-op (the schema_version table is created by
``_init_schema``); v2-v5 land their respective objects in the schema DDL
itself, so the migration entries here exist primarily to register the
versions and stay forward-compatible with future deltas.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from seerflow.storage._mitre_backfill import decode_alert_for_backfill

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import asyncpg

logger = logging.getLogger(__name__)


_BACKFILL_CHUNK = 1000


async def _migrate_v1_bootstrap(conn: asyncpg.Connection) -> None:
    """Migration 1: ensure the ``schema_version`` table exists.

    ``_init_schema`` already creates the table on first run; this migration
    only re-asserts it for older Postgres DBs that pre-date the bootstrap
    DDL. Idempotent.
    """
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "    version INTEGER NOT NULL UNIQUE,"
        "    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
        ")"
    )


async def _migrate_v2_graph_edges(conn: asyncpg.Connection) -> None:
    """Migration 2: graph_edges table (idempotent — schema DDL already creates it)."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS graph_edges ("
        "    source_id TEXT NOT NULL,"
        "    target_id TEXT NOT NULL,"
        "    rel_type TEXT NOT NULL,"
        "    first_seen BIGINT NOT NULL,"
        "    last_seen BIGINT NOT NULL,"
        "    event_count INTEGER NOT NULL DEFAULT 1,"
        "    PRIMARY KEY (source_id, target_id, rel_type)"
        ")"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id)"
    )


async def _migrate_v3_mitre_junctions(conn: asyncpg.Connection) -> None:
    """Migration 3: MITRE junction tables + backfill.

    Tables denormalise ``timestamp_ns`` from ``alerts`` so the composite
    ``(tactic|technique, timestamp_ns DESC)`` index can drive both the
    filter and the ORDER BY without scanning the alerts table.
    """
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS alert_tactics ("
        "    dedup_key TEXT NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,"
        "    tactic TEXT NOT NULL,"
        "    timestamp_ns BIGINT NOT NULL,"
        "    PRIMARY KEY (dedup_key, tactic)"
        ")"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_tactics_tactic_time "
        "ON alert_tactics(tactic, timestamp_ns DESC)"
    )
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS alert_techniques ("
        "    dedup_key TEXT NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,"
        "    technique TEXT NOT NULL,"
        "    timestamp_ns BIGINT NOT NULL,"
        "    PRIMARY KEY (dedup_key, technique)"
        ")"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_techniques_technique_time "
        "ON alert_techniques(technique, timestamp_ns DESC)"
    )
    await _backfill_mitre_junctions(conn)


async def _backfill_mitre_junctions(conn: asyncpg.Connection) -> None:
    """Stream existing alerts, decode msgpack, populate junction rows."""
    table_row = await conn.fetchrow("SELECT to_regclass('alerts') AS reg")
    if table_row is None or table_row["reg"] is None:
        return

    offset = 0
    processed = 0
    while True:
        rows = await conn.fetch(
            "SELECT dedup_key, timestamp_ns, data FROM alerts "
            "ORDER BY dedup_key LIMIT $1 OFFSET $2",
            _BACKFILL_CHUNK,
            offset,
        )
        if not rows:
            break

        tactic_rows: list[tuple[str, str, int]] = []
        technique_rows: list[tuple[str, str, int]] = []
        for row in rows:
            dedup_key = row["dedup_key"]
            ts_ns = int(row["timestamp_ns"])
            blob = row["data"]
            decoded = decode_alert_for_backfill(
                bytes(blob) if blob is not None else None, ts_ns, dedup_key
            )
            if decoded is None:
                continue
            tactics, techniques = decoded
            tactic_rows.extend((dedup_key, t, ts_ns) for t in tactics)
            technique_rows.extend((dedup_key, t, ts_ns) for t in techniques)

        if tactic_rows:
            await conn.executemany(
                "INSERT INTO alert_tactics (dedup_key, tactic, timestamp_ns) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                tactic_rows,
            )
        if technique_rows:
            await conn.executemany(
                "INSERT INTO alert_techniques (dedup_key, technique, timestamp_ns) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                technique_rows,
            )

        offset += _BACKFILL_CHUNK
        processed += len(rows)
        if processed % (_BACKFILL_CHUNK * 10) == 0:
            logger.info("v3 backfill: processed %d alerts", processed)


async def _migrate_v4_feedback_events(conn: asyncpg.Connection) -> None:
    """Migration 4: append-only TP/FP feedback audit log."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS alert_feedback_events ("
        "    id BIGSERIAL PRIMARY KEY,"
        "    alert_id TEXT NOT NULL,"
        "    feedback TEXT NOT NULL CHECK (feedback IN ('tp','fp')),"
        "    note TEXT NOT NULL DEFAULT '',"
        "    origin TEXT NOT NULL CHECK (origin IN ('dashboard','cli','api')),"
        "    submitted_at_ns BIGINT NOT NULL"
        ")"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_alert_time "
        "ON alert_feedback_events(alert_id, submitted_at_ns DESC)"
    )


async def _migrate_v5_sigma_rule_state(conn: asyncpg.Connection) -> None:
    """Migration 5: per-rule Sigma state — enabled flag + match counters."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS sigma_rule_state ("
        "    rule_id TEXT PRIMARY KEY,"
        "    enabled INTEGER NOT NULL DEFAULT 1,"
        "    match_count_lifetime BIGINT NOT NULL DEFAULT 0,"
        "    last_fired_ns BIGINT,"
        "    updated_at_ns BIGINT NOT NULL"
        ")"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sigma_rule_state_enabled ON sigma_rule_state(enabled)"
    )


async def _migrate_v6_junction_timestamp_ns(conn: asyncpg.Connection) -> None:
    """Migration 6: junction backfill / index reshape.

    Postgres no-op — the v3 migration already lands the denormalised
    ``timestamp_ns`` column directly. Kept in the ledger so version numbers
    stay in sync with the SQLite list.
    """
    return None


MIGRATIONS: dict[int, Callable[[asyncpg.Connection], Awaitable[None]]] = {
    1: _migrate_v1_bootstrap,
    2: _migrate_v2_graph_edges,
    3: _migrate_v3_mitre_junctions,
    4: _migrate_v4_feedback_events,
    5: _migrate_v5_sigma_rule_state,
    6: _migrate_v6_junction_timestamp_ns,
}


async def get_pg_schema_version(conn: asyncpg.Connection) -> int:
    """Return the current schema version (0 if the ledger is empty)."""
    try:
        row = await conn.fetchrow("SELECT MAX(version) AS v FROM schema_version")
    except Exception as exc:  # pragma: no cover — surfaced only when DDL still missing
        msg = str(exc).lower()
        if "does not exist" in msg or "undefined" in msg:
            return 0
        raise
    if row is None or row["v"] is None:
        return 0
    return int(row["v"])


async def run_pg_migrations(conn: asyncpg.Connection) -> int:
    """Apply pending Postgres migrations and return the count applied.

    Each migration runs inside its own transaction.
    """
    current = await get_pg_schema_version(conn)
    applied = 0
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        logger.info("Applying Postgres schema migration %d", version)
        async with conn.transaction():
            await MIGRATIONS[version](conn)
            await conn.execute("INSERT INTO schema_version (version) VALUES ($1)", version)
        applied += 1
    return applied
