"""Integration tests — Drain3 persistence with real SqliteBackend."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

from seerflow.config import StorageConfig
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.drain_persistence import load_drain_state, save_drain_state
from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    db_path = str(tmp_path / "test.db")
    config = StorageConfig(backend="sqlite", sqlite_path=db_path)
    backend = await SqliteBackend.connect(config)
    yield backend
    await backend.close()


class TestDrainSqlitePersistence:
    async def test_full_cycle(self, backend: SqliteBackend) -> None:
        parser = DrainParser()
        tid1, _, _ = parser.parse("Login failed for user alice")
        tid2, _, _ = parser.parse("Connection established to db01")

        await save_drain_state(parser, backend)

        parser2 = DrainParser()
        loaded = await load_drain_state(parser2, backend)

        assert loaded is True
        assert parser2.template_count == parser.template_count

        tid1b, _, _ = parser2.parse("Login failed for user bob")
        tid2b, _, _ = parser2.parse("Connection established to db02")
        assert tid1b == tid1
        assert tid2b == tid2

    async def test_overwrite(self, backend: SqliteBackend) -> None:
        parser = DrainParser()
        parser.parse("First pattern alpha")
        await save_drain_state(parser, backend)

        parser.parse("Second pattern beta")
        await save_drain_state(parser, backend)

        parser2 = DrainParser()
        await load_drain_state(parser2, backend)
        assert parser2.template_count == parser.template_count

    async def test_independent_keys(self, backend: SqliteBackend) -> None:
        parser_a = DrainParser()
        parser_a.parse("Pattern for source A")
        await save_drain_state(parser_a, backend, key="drain3:source_a")

        parser_b = DrainParser()
        parser_b.parse("Pattern for source B")
        parser_b.parse("Another pattern for B")
        await save_drain_state(parser_b, backend, key="drain3:source_b")

        restored_a = DrainParser()
        await load_drain_state(restored_a, backend, key="drain3:source_a")
        assert restored_a.template_count == 1

        restored_b = DrainParser()
        await load_drain_state(restored_b, backend, key="drain3:source_b")
        assert restored_b.template_count == 2

    async def test_first_run_no_state(self, backend: SqliteBackend) -> None:
        parser = DrainParser()
        loaded = await load_drain_state(parser, backend)
        assert loaded is False
        assert parser.template_count == 0
