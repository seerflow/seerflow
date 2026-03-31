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


MIGRATIONS: dict[int, Callable[[aiosqlite.Connection], Awaitable[None]]] = {
    1: _migrate_v1_bootstrap,
    2: _migrate_v2_graph_edges,
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
