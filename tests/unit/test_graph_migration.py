"""Tests for graph_edges schema migration (v2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestGraphEdgesMigration:
    @pytest.mark.asyncio()
    async def test_migration_creates_graph_edges_table(self, tmp_path: Path) -> None:
        """Migration v2 creates the graph_edges table."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            from seerflow.storage.migrations import run_migrations

            await run_migrations(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_edges'"
            )
            row = await cursor.fetchone()
            assert row is not None

    @pytest.mark.asyncio()
    async def test_graph_edges_upsert(self, tmp_path: Path) -> None:
        """UPSERT increments event_count and updates last_seen on conflict."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            from seerflow.storage.migrations import run_migrations

            await run_migrations(conn)
            await conn.execute(
                "INSERT INTO graph_edges"
                " (source_id,target_id,rel_type,"
                "first_seen,last_seen,event_count)"
                " VALUES (?,?,?,?,?,?)",
                ("a", "b", "has_ip", 100, 100, 1),
            )
            await conn.execute(
                "INSERT INTO graph_edges"
                " (source_id,target_id,rel_type,"
                "first_seen,last_seen,event_count)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(source_id,target_id,rel_type)"
                " DO UPDATE SET"
                " last_seen=MAX(last_seen,excluded.last_seen),"
                " event_count=event_count+1",
                ("a", "b", "has_ip", 200, 200, 1),
            )
            await conn.commit()
            cursor = await conn.execute("SELECT event_count, last_seen FROM graph_edges")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 2
            assert row[1] == 200

    @pytest.mark.asyncio()
    async def test_graph_edges_indexes_exist(self, tmp_path: Path) -> None:
        """Migration v2 creates source and target indexes."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            from seerflow.storage.migrations import run_migrations

            await run_migrations(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name LIKE 'idx_graph_edges%'"
            )
            rows = await cursor.fetchall()
            index_names = {r[0] for r in rows}
            assert "idx_graph_edges_source" in index_names
            assert "idx_graph_edges_target" in index_names
