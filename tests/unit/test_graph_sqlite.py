"""Tests for graph edge SQLite persistence via SqliteBackend."""

from __future__ import annotations

import pytest

from seerflow.config import StorageConfig
from seerflow.storage.sqlite import SqliteBackend


class TestGraphEdgeSqlite:
    @pytest.fixture()
    async def backend(self, tmp_path):
        config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        b = await SqliteBackend.connect(config)
        yield b
        await b.close()

    @pytest.mark.asyncio()
    async def test_write_and_load_edges(self, backend: SqliteBackend) -> None:
        await backend.write_edge("a", "b", "has_ip", 1000)
        await backend.write_edge("b", "c", "logged_into", 2000)
        rows = await backend.load_edges()
        assert len(rows) == 2

    @pytest.mark.asyncio()
    async def test_upsert_increments_count(self, backend: SqliteBackend) -> None:
        await backend.write_edge("a", "b", "has_ip", 1000)
        await backend.write_edge("a", "b", "has_ip", 2000)
        rows = await backend.load_edges()
        assert len(rows) == 1
        assert rows[0][4] == 2000  # last_seen
        assert rows[0][5] == 2  # event_count

    @pytest.mark.asyncio()
    async def test_load_edges_empty_db(self, backend: SqliteBackend) -> None:
        rows = await backend.load_edges()
        assert rows == []

    @pytest.mark.asyncio()
    async def test_write_edge_preserves_first_seen(self, backend: SqliteBackend) -> None:
        await backend.write_edge("a", "b", "has_ip", 1000)
        await backend.write_edge("a", "b", "has_ip", 500)
        rows = await backend.load_edges()
        assert rows[0][3] == 1000  # first_seen preserved (MAX keeps the original)
