"""Tests for the SQLite schema migration system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest

from seerflow.storage.migrations import MIGRATIONS, get_schema_version, run_migrations


class TestSchemaVersion:
    @pytest.mark.asyncio()
    async def test_fresh_db_returns_version_0(self, tmp_path: Path) -> None:
        """A fresh database with no schema_version table reports version 0."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            version = await get_schema_version(conn)
        assert version == 0

    @pytest.mark.asyncio()
    async def test_versioned_db_returns_correct_version(self, tmp_path: Path) -> None:
        """A database with schema_version table reports the stored version."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(
                "CREATE TABLE schema_version (version INTEGER NOT NULL UNIQUE, applied_at TEXT)"
            )
            await conn.execute("INSERT INTO schema_version (version) VALUES (3)")
            await conn.commit()
            version = await get_schema_version(conn)
        assert version == 3


class TestRunMigrations:
    @pytest.mark.asyncio()
    async def test_fresh_db_applies_all_migrations(self, tmp_path: Path) -> None:
        """All registered migrations are applied on a fresh database."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            applied = await run_migrations(conn)
            assert applied == len(MIGRATIONS)
            version = await get_schema_version(conn)
            assert version == max(MIGRATIONS)

    @pytest.mark.asyncio()
    async def test_already_at_latest_applies_nothing(self, tmp_path: Path) -> None:
        """A database at the latest version has no migrations to apply."""
        db_path = tmp_path / "test.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            await run_migrations(conn)
            applied = await run_migrations(conn)
            assert applied == 0

    @pytest.mark.asyncio()
    async def test_migration_failure_rolls_back(self, tmp_path: Path) -> None:
        """If a migration fails, the transaction is rolled back."""
        db_path = tmp_path / "test.db"
        latest = max(MIGRATIONS)
        async with aiosqlite.connect(str(db_path)) as conn:
            await run_migrations(conn)

            async def _broken(c: aiosqlite.Connection) -> None:
                raise RuntimeError("migration failed")

            next_version = latest + 1
            with (
                patch.dict(
                    "seerflow.storage.migrations.MIGRATIONS",
                    {**MIGRATIONS, next_version: _broken},
                ),
                pytest.raises(RuntimeError, match="migration failed"),
            ):
                await run_migrations(conn)

            version = await get_schema_version(conn)
            assert version == latest

    @pytest.mark.asyncio()
    async def test_migrations_applied_in_order(self, tmp_path: Path) -> None:
        """Migrations are applied in ascending version order."""
        db_path = tmp_path / "test.db"
        latest = max(MIGRATIONS)
        async with aiosqlite.connect(str(db_path)) as conn:
            await run_migrations(conn)

            order: list[int] = []
            v_a = latest + 1
            v_b = latest + 2

            async def _ma(c: aiosqlite.Connection) -> None:
                order.append(v_a)

            async def _mb(c: aiosqlite.Connection) -> None:
                order.append(v_b)

            with patch.dict(
                "seerflow.storage.migrations.MIGRATIONS",
                {**MIGRATIONS, v_a: _ma, v_b: _mb},
            ):
                applied = await run_migrations(conn)
                assert applied == 2
                assert order == [v_a, v_b]
                version = await get_schema_version(conn)
                assert version == v_b


class TestSqliteBackendMigration:
    @pytest.mark.asyncio()
    async def test_backend_connect_runs_migrations(self, tmp_path: Path) -> None:
        """SqliteBackend.connect() applies pending migrations on startup."""
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(
            data_dir=str(tmp_path),
            sqlite_path=str(tmp_path / "test.db"),
        )
        storage = await SqliteBackend.connect(config)
        try:
            version = await get_schema_version(storage._conn)
            assert version >= 1
        finally:
            await storage.close()

    @pytest.mark.asyncio()
    async def test_backend_reconnect_no_duplicate_migrations(self, tmp_path: Path) -> None:
        """Reconnecting to an existing database does not re-run migrations."""
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(
            data_dir=str(tmp_path),
            sqlite_path=str(tmp_path / "test.db"),
        )
        storage1 = await SqliteBackend.connect(config)
        await storage1.close()

        storage2 = await SqliteBackend.connect(config)
        try:
            version = await get_schema_version(storage2._conn)
            assert version == max(MIGRATIONS)
        finally:
            await storage2.close()


@pytest.mark.asyncio
async def test_migration_v3_registered_and_applied(tmp_path: Path) -> None:
    assert 3 in MIGRATIONS
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await run_migrations(conn)
        assert await get_schema_version(conn) >= 3
