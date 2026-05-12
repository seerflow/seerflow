"""SQLite schema migration system.

Provides a lightweight migration runner that tracks schema versions
and applies pending migrations in order within transactions.

Migration functions are registered in the ``MIGRATIONS`` dict, keyed
by version number (1, 2, 3, ...). Each function receives an
``aiosqlite.Connection`` and must perform its DDL/DML within the
current transaction.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiosqlite

from seerflow.storage._mitre_backfill import decode_alert_for_backfill

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def _migrate_v1_bootstrap(conn: aiosqlite.Connection) -> None:
    """Migration 1: Add schema_version table.

    The main schema DDL (events, alerts, etc.) is already created by
    ``_init_schema()`` before the migration runner is called. This
    migration just adds version tracking.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER NOT NULL UNIQUE,
            applied_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)


async def _migrate_v2_graph_edges(conn: aiosqlite.Connection) -> None:
    """Create graph_edges table for entity relationship persistence."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            source_id   TEXT    NOT NULL,
            target_id   TEXT    NOT NULL,
            rel_type    TEXT    NOT NULL,
            first_seen  INTEGER NOT NULL,
            last_seen   INTEGER NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(source_id, target_id, rel_type)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id)"
    )


async def _migrate_v3_mitre_junctions(conn: aiosqlite.Connection) -> None:
    """Migration 3: junction tables for tactic/technique filtering + backfill.

    Tables denormalize ``timestamp_ns`` from ``alerts`` so the composite
    ``(tactic|technique, timestamp_ns DESC)`` index can drive both the filter
    and the ORDER BY without touching the main alerts table — the query plan
    becomes a seek on the junction index joined back to ``alerts`` by PK.
    """
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_tactics (
            dedup_key    TEXT    NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,
            tactic       TEXT    NOT NULL,
            timestamp_ns INTEGER NOT NULL,
            PRIMARY KEY (dedup_key, tactic)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_tactics_tactic_time "
        "ON alert_tactics(tactic, timestamp_ns DESC)"
    )
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_techniques (
            dedup_key    TEXT    NOT NULL REFERENCES alerts(dedup_key) ON DELETE CASCADE,
            technique    TEXT    NOT NULL,
            timestamp_ns INTEGER NOT NULL,
            PRIMARY KEY (dedup_key, technique)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_techniques_technique_time "
        "ON alert_techniques(technique, timestamp_ns DESC)"
    )

    await _backfill_mitre_junctions(conn)


_BACKFILL_CHUNK = 1000


async def _backfill_mitre_junctions(conn: aiosqlite.Connection) -> None:
    """Stream existing alerts, decode msgpack, populate junction rows."""
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
    ) as cur:
        if await cur.fetchone() is None:
            return

    offset = 0
    processed = 0
    while True:
        async with conn.execute(
            "SELECT dedup_key, timestamp_ns, data FROM alerts ORDER BY rowid LIMIT ? OFFSET ?",
            (_BACKFILL_CHUNK, offset),
        ) as cur:
            rows = list(await cur.fetchall())
        if not rows:
            break

        tactic_rows: list[tuple[str, str, int]] = []
        technique_rows: list[tuple[str, str, int]] = []
        for dedup_key, ts_ns, blob in rows:
            decoded = decode_alert_for_backfill(blob, ts_ns, dedup_key)
            if decoded is None:
                continue
            tactics, techniques = decoded
            tactic_rows.extend((dedup_key, t, ts_ns) for t in tactics)
            technique_rows.extend((dedup_key, t, ts_ns) for t in techniques)

        if tactic_rows:
            await conn.executemany(
                "INSERT OR IGNORE INTO alert_tactics "
                "(dedup_key, tactic, timestamp_ns) VALUES (?, ?, ?)",
                tactic_rows,
            )
        if technique_rows:
            await conn.executemany(
                "INSERT OR IGNORE INTO alert_techniques "
                "(dedup_key, technique, timestamp_ns) VALUES (?, ?, ?)",
                technique_rows,
            )

        offset += _BACKFILL_CHUNK
        processed += len(rows)
        if processed % (_BACKFILL_CHUNK * 10) == 0:
            logger.info("v3 backfill: processed %d alerts", processed)
        # Commit per-chunk to release WAL pressure on large backfills.
        await conn.commit()


async def _migrate_v4_feedback_events(conn: aiosqlite.Connection) -> None:
    """Migration 4: append-only TP/FP feedback audit log (S-066)."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_feedback_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id        TEXT    NOT NULL,
            feedback        TEXT    NOT NULL CHECK (feedback IN ('tp','fp')),
            note            TEXT    NOT NULL DEFAULT '',
            origin          TEXT    NOT NULL CHECK (origin IN ('dashboard','cli','api')),
            submitted_at_ns INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_alert_time "
        "ON alert_feedback_events(alert_id, submitted_at_ns DESC)"
    )


async def _migrate_v5_sigma_rule_state(conn: aiosqlite.Connection) -> None:
    """Migration 5: per-rule Sigma state — enabled flag + match counters (S-151)."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sigma_rule_state (
            rule_id              TEXT    PRIMARY KEY,
            enabled              INTEGER NOT NULL DEFAULT 1,
            match_count_lifetime INTEGER NOT NULL DEFAULT 0,
            last_fired_ns        INTEGER,
            updated_at_ns        INTEGER NOT NULL
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sigma_rule_state_enabled ON sigma_rule_state(enabled)"
    )


async def _column_exists(conn: aiosqlite.Connection, table: str, column: str) -> bool:
    async with conn.execute(f"PRAGMA table_info({table})") as cur:  # nosec B608
        return any(row[1] == column for row in await cur.fetchall())


async def _migrate_v6_junction_timestamp_ns(conn: aiosqlite.Connection) -> None:
    """Migration 6: backfill ``timestamp_ns`` on mitre junction tables for
    DBs created before the v3 denormalize landed.

    v3 was originally shipped without ``timestamp_ns`` on the junctions; the
    denormalization was added later and only takes effect for fresh DBs
    where ``CREATE TABLE`` includes the column. Pre-existing DBs need an
    explicit ALTER + backfill + reindex so the SQL plan in
    ``query_alerts`` (ORDER BY ``at.timestamp_ns``) does not blow up with
    ``no such column``.
    """
    for table in ("alert_tactics", "alert_techniques"):
        if not await _column_exists(conn, table, "timestamp_ns"):
            await conn.execute(
                f"ALTER TABLE {table} ADD COLUMN timestamp_ns INTEGER NOT NULL DEFAULT 0"  # nosec B608
            )
            await conn.execute(
                f"UPDATE {table} SET timestamp_ns = ("  # noqa: S608  # nosec B608
                f"  SELECT a.timestamp_ns FROM alerts a "
                f"  WHERE a.dedup_key = {table}.dedup_key)"
            )

    await conn.execute("DROP INDEX IF EXISTS idx_alert_tactics_tactic")
    await conn.execute("DROP INDEX IF EXISTS idx_alert_techniques_technique")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_tactics_tactic_time "
        "ON alert_tactics(tactic, timestamp_ns DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_techniques_technique_time "
        "ON alert_techniques(technique, timestamp_ns DESC)"
    )


MIGRATIONS: dict[int, Callable[[aiosqlite.Connection], Awaitable[None]]] = {
    1: _migrate_v1_bootstrap,
    2: _migrate_v2_graph_edges,
    3: _migrate_v3_mitre_junctions,
    4: _migrate_v4_feedback_events,
    5: _migrate_v5_sigma_rule_state,
    6: _migrate_v6_junction_timestamp_ns,
}


async def get_schema_version(conn: aiosqlite.Connection) -> int:
    """Return the current schema version (0 if no schema_version table)."""
    try:
        async with conn.execute("SELECT MAX(version) FROM schema_version") as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0
    except aiosqlite.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return 0
        raise  # do not mask unexpected DB errors


async def run_migrations(conn: aiosqlite.Connection) -> int:
    """Apply pending migrations and return the count applied.

    Each migration runs in its own transaction. On failure, the
    transaction is rolled back and the error is re-raised.
    """
    current = await get_schema_version(conn)
    applied = 0

    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        logger.info("Applying schema migration %d", version)
        try:
            await MIGRATIONS[version](conn)
            await conn.execute("INSERT INTO schema_version (version) VALUES (?)", [version])
            await conn.commit()
            applied += 1
        except Exception:
            await conn.rollback()
            logger.error("Schema migration %d failed — rolled back", version, exc_info=True)
            raise

    return applied
