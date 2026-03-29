"""Tests for the SQLite schema migration system."""

from __future__ import annotations

import aiosqlite
import pytest


class TestSchemaVersion:
    @pytest.mark.asyncio()
    async def test_fresh_db_returns_version_0(self, tmp_path: object) -> None:
        """A fresh database with no schema_version table reports version 0."""
        from seerflow.storage.migrations import get_schema_version

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            version = await get_schema_version(conn)
        assert version == 0

    @pytest.mark.asyncio()
    async def test_versioned_db_returns_correct_version(self, tmp_path: object) -> None:
        """A database with schema_version table reports the stored version."""
        from seerflow.storage.migrations import get_schema_version

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(
                "CREATE TABLE schema_version (version INTEGER NOT NULL, applied_at TEXT)"
            )
            await conn.execute("INSERT INTO schema_version (version) VALUES (3)")
            await conn.commit()
            version = await get_schema_version(conn)
        assert version == 3


class TestRunMigrations:
    @pytest.mark.asyncio()
    async def test_fresh_db_applies_migration_1(self, tmp_path: object) -> None:
        """Migration 1 creates the schema_version table on a fresh database."""
        from seerflow.storage.migrations import get_schema_version, run_migrations

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            applied = await run_migrations(conn)
            assert applied == 1
            version = await get_schema_version(conn)
            assert version == 1

    @pytest.mark.asyncio()
    async def test_already_at_latest_applies_nothing(self, tmp_path: object) -> None:
        """A database at the latest version has no migrations to apply."""
        from seerflow.storage.migrations import run_migrations

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            await run_migrations(conn)  # apply all
            applied = await run_migrations(conn)  # run again
            assert applied == 0

    @pytest.mark.asyncio()
    async def test_migration_failure_rolls_back(self, tmp_path: object) -> None:
        """If a migration fails, the transaction is rolled back."""
        from seerflow.storage.migrations import MIGRATIONS, get_schema_version, run_migrations

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            # Apply migration 1 first
            await run_migrations(conn)

            # Add a broken migration 2
            original = dict(MIGRATIONS)
            try:

                async def _broken(c: aiosqlite.Connection) -> None:
                    raise RuntimeError("migration failed")

                MIGRATIONS[2] = _broken
                with pytest.raises(RuntimeError, match="migration failed"):
                    await run_migrations(conn)

                # Version should still be 1 (rolled back)
                version = await get_schema_version(conn)
                assert version == 1
            finally:
                MIGRATIONS.clear()
                MIGRATIONS.update(original)

    @pytest.mark.asyncio()
    async def test_migrations_applied_in_order(self, tmp_path: object) -> None:
        """Migrations are applied in ascending version order."""
        from seerflow.storage.migrations import MIGRATIONS, get_schema_version, run_migrations

        db_path = tmp_path / "test.db"  # type: ignore[operator]
        async with aiosqlite.connect(str(db_path)) as conn:
            # Apply migration 1
            await run_migrations(conn)

            # Add migrations 2 and 3
            original = dict(MIGRATIONS)
            order: list[int] = []
            try:

                async def _m2(c: aiosqlite.Connection) -> None:
                    order.append(2)

                async def _m3(c: aiosqlite.Connection) -> None:
                    order.append(3)

                MIGRATIONS[2] = _m2
                MIGRATIONS[3] = _m3
                applied = await run_migrations(conn)
                assert applied == 2
                assert order == [2, 3]
                version = await get_schema_version(conn)
                assert version == 3
            finally:
                MIGRATIONS.clear()
                MIGRATIONS.update(original)


class TestSqliteBackendMigration:
    @pytest.mark.asyncio()
    async def test_backend_connect_runs_migrations(self, tmp_path: object) -> None:
        """SqliteBackend.connect() applies pending migrations on startup."""
        from seerflow.config import StorageConfig
        from seerflow.storage.migrations import get_schema_version
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(
            data_dir=str(tmp_path),
            sqlite_path=str(tmp_path / "test.db"),  # type: ignore[operator]
        )
        storage = await SqliteBackend.connect(config)
        try:
            version = await get_schema_version(storage._conn)
            assert version >= 1
        finally:
            await storage.close()

    @pytest.mark.asyncio()
    async def test_backend_reconnect_no_duplicate_migrations(self, tmp_path: object) -> None:
        """Reconnecting to an existing database does not re-run migrations."""
        from seerflow.config import StorageConfig
        from seerflow.storage.migrations import get_schema_version
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(
            data_dir=str(tmp_path),
            sqlite_path=str(tmp_path / "test.db"),  # type: ignore[operator]
        )
        # First connect — applies migrations
        storage1 = await SqliteBackend.connect(config)
        await storage1.close()

        # Second connect — should not re-run
        storage2 = await SqliteBackend.connect(config)
        try:
            version = await get_schema_version(storage2._conn)
            assert version == 1  # still at 1, not 2
        finally:
            await storage2.close()
