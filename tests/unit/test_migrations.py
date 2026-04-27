"""Tests for the SQLite schema migration system."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import aiosqlite
import msgspec
import pytest

from seerflow.models.alert import Alert
from seerflow.storage.migrations import MIGRATIONS, get_schema_version, run_migrations

if TYPE_CHECKING:
    from pathlib import Path


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


async def _seed_v2_alert(
    conn: aiosqlite.Connection,
    *,
    dedup_key: str,
    tactics: tuple[str, ...],
    techniques: tuple[str, ...],
) -> None:
    alert = Alert(
        alert_id="a1",
        alert_type="sigma",
        timestamp_ns=1,
        severity_id=3,
        rule_name="r",
        description="d",
        entity_uuid="e",
        entity_type="host",
        entity_value="v",
        contributing_events=(),
        dedup_key=dedup_key,
        dedup_count=1,
        risk_score=0.0,
        feedback="",
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )
    await conn.execute(
        "INSERT INTO alerts (alert_id, alert_type, timestamp_ns, severity_id, "
        "rule_name, entity_uuid, entity_type, entity_value, dedup_key, "
        "dedup_count, risk_score, feedback, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
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
            msgspec.msgpack.encode(alert),
        ),
    )


@pytest.mark.asyncio
async def test_migration_v3_backfills_existing_rows(tmp_path: Path) -> None:
    from seerflow.storage.sqlite import _init_schema

    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await _init_schema(conn)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        await conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        await conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        await _seed_v2_alert(
            conn,
            dedup_key="k1",
            tactics=("discovery", "execution"),
            techniques=("T1059.001", "t1059"),
        )
        await conn.commit()

        await run_migrations(conn)

        async with conn.execute(
            "SELECT tactic FROM alert_tactics WHERE dedup_key='k1' ORDER BY tactic"
        ) as cur:
            tactics = [r[0] for r in await cur.fetchall()]
        async with conn.execute(
            "SELECT technique FROM alert_techniques WHERE dedup_key='k1' ORDER BY technique"
        ) as cur:
            techs = [r[0] for r in await cur.fetchall()]

    assert tactics == ["discovery", "execution"]
    assert techs == ["T1059", "T1059.001"]


@pytest.mark.asyncio
async def test_migration_v3_tolerates_none_mitre_fields(tmp_path: Path) -> None:
    """Alerts whose decoded form has None tactic/technique fields don't abort."""
    from seerflow.storage import migrations as migrations_module
    from seerflow.storage.sqlite import _init_schema

    class _FakeAlert:
        mitre_tactics = None
        mitre_techniques = None

    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await _init_schema(conn)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        await conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        await conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        await _seed_v2_alert(
            conn,
            dedup_key="k_none",
            tactics=("discovery",),
            techniques=("T1059",),
        )
        await conn.commit()

        with patch.object(migrations_module.msgspec.msgpack, "decode", return_value=_FakeAlert()):
            await run_migrations(conn)

        assert await get_schema_version(conn) >= 3
        async with conn.execute(
            "SELECT COUNT(*) FROM alert_tactics WHERE dedup_key='k_none'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == 0


@pytest.mark.asyncio
async def test_migration_v3_skips_corrupt_blob(tmp_path: Path) -> None:
    from seerflow.storage.sqlite import _init_schema

    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await _init_schema(conn)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        await conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        await conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        await conn.execute(
            "INSERT INTO alerts (alert_id, alert_type, timestamp_ns, severity_id, "
            "rule_name, entity_uuid, entity_type, entity_value, dedup_key, "
            "dedup_count, risk_score, feedback, data) "
            "VALUES ('a','t',1,3,'r','e','host','v','k_bad',1,0.0,NULL,?)",
            (b"\x00\x01not-msgpack",),
        )
        await conn.commit()
        await run_migrations(conn)
        assert await get_schema_version(conn) >= 3


@pytest.mark.asyncio
async def test_migration_v4_creates_feedback_events_table(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE alerts (alert_id TEXT, dedup_key TEXT, timestamp_ns INTEGER, data BLOB)"
        )
        await conn.commit()
        applied = await run_migrations(conn)
        assert applied >= 4

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_feedback_events'"
        ) as cur:
            assert await cur.fetchone() is not None

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_feedback_alert_time'"
        ) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_migration_v4_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "t.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE alerts (alert_id TEXT, dedup_key TEXT, timestamp_ns INTEGER, data BLOB)"
        )
        await conn.commit()
        await run_migrations(conn)
        applied2 = await run_migrations(conn)
        assert applied2 == 0


@pytest.mark.asyncio
async def test_migration_v6_adds_timestamp_ns_to_pre_existing_junctions(
    tmp_path: Path,
) -> None:
    """Pre-v6 DBs have junctions without ``timestamp_ns``; v6 ALTERs + backfills."""
    db_path = tmp_path / "t.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE alerts (dedup_key TEXT PRIMARY KEY, timestamp_ns INTEGER)"
        )
        await conn.execute(
            "CREATE TABLE alert_tactics ("
            "  dedup_key TEXT REFERENCES alerts(dedup_key), tactic TEXT, "
            "  PRIMARY KEY (dedup_key, tactic))"
        )
        await conn.execute(
            "CREATE TABLE alert_techniques ("
            "  dedup_key TEXT REFERENCES alerts(dedup_key), technique TEXT, "
            "  PRIMARY KEY (dedup_key, technique))"
        )
        await conn.execute("CREATE INDEX idx_alert_tactics_tactic ON alert_tactics(tactic)")
        await conn.execute(
            "CREATE INDEX idx_alert_techniques_technique ON alert_techniques(technique)"
        )
        await conn.execute(
            "CREATE TABLE schema_version ("
            "  version INTEGER NOT NULL UNIQUE, "
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        for v in (1, 2, 3, 4, 5):
            await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
        await conn.execute("INSERT INTO alerts VALUES ('k1', 1234)")
        await conn.execute("INSERT INTO alert_tactics VALUES ('k1', 'reconnaissance')")
        await conn.execute("INSERT INTO alert_techniques VALUES ('k1', 't1595')")
        await conn.commit()

        applied = await run_migrations(conn)
        assert applied == 1
        assert await get_schema_version(conn) == 6

        async with conn.execute(
            "SELECT timestamp_ns FROM alert_tactics WHERE dedup_key='k1'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1234
        async with conn.execute(
            "SELECT timestamp_ns FROM alert_techniques WHERE dedup_key='k1'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1234

        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_alert_tactics_tactic_time'"
        ) as cur:
            assert await cur.fetchone() is not None


@pytest.mark.asyncio
async def test_migration_v6_idempotent_on_fresh_db(tmp_path: Path) -> None:
    """Fresh DBs already have ``timestamp_ns`` from v3; v6 must be a no-op."""
    db_path = tmp_path / "t.db"
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "CREATE TABLE alerts (alert_id TEXT, dedup_key TEXT, timestamp_ns INTEGER, data BLOB)"
        )
        await conn.commit()
        await run_migrations(conn)
        applied2 = await run_migrations(conn)
        assert applied2 == 0
