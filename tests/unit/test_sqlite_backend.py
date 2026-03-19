"""Tests for SqliteBackend — schema creation, event batch writes."""

from __future__ import annotations

import json
import uuid

import aiosqlite
import msgspec
import pytest

from seerflow.config import ConfigError, StorageConfig
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.storage.protocols import LogStore
from seerflow.storage.sqlite import SqliteBackend, _init_schema, _validate_path


class TestPathValidation:
    def test_null_byte_rejected(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/bad\x00path.db")

    def test_null_byte_in_middle(self) -> None:
        with pytest.raises(ConfigError, match="null byte"):
            _validate_path("/tmp/some\x00/dir/file.db")

    def test_valid_path_passes(self) -> None:
        _validate_path("/tmp/valid/path/seerflow.db")

    def test_empty_path_passes(self) -> None:
        _validate_path("")


class TestSchema:
    async def _init_memory_db(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(":memory:")
        await _init_schema(conn)
        return conn

    async def test_events_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_entity_events_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='entity_events'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_alerts_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_model_state_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='model_state'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_fts5_table_exists(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await conn.close()

    async def test_events_indexes_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_events_%'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
            assert indexes == {
                "idx_events_time",
                "idx_events_source_sev",
                "idx_events_template",
            }
        finally:
            await conn.close()

    async def test_alerts_indexes_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_alerts_%'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
            assert indexes == {
                "idx_alerts_time",
                "idx_alerts_entity",
                "idx_alerts_dedup",
                "idx_alerts_type",
            }
        finally:
            await conn.close()

    async def test_fts_triggers_exist(self) -> None:
        conn = await self._init_memory_db()
        try:
            cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
            triggers = {row[0] for row in await cursor.fetchall()}
            assert triggers == {
                "events_fts_insert",
                "events_fts_delete",
                "events_fts_update",
            }
        finally:
            await conn.close()

    async def test_schema_idempotent(self) -> None:
        conn = await aiosqlite.connect(":memory:")
        try:
            await _init_schema(conn)
            await _init_schema(conn)
        finally:
            await conn.close()


class TestSqliteBackendLifecycle:
    async def test_connect_returns_backend(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            assert isinstance(backend, SqliteBackend)
        finally:
            await backend.close()

    async def test_isinstance_log_store(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            assert isinstance(backend, LogStore)
        finally:
            await backend.close()

    async def test_schema_created_on_connect(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            cursor = await backend._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await backend.close()

    async def test_close_is_idempotent(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        await backend.close()
        await backend.close()  # no error


def _make_event(
    *,
    message: str = "test event",
    severity: SeverityLevel = SeverityLevel.INFORMATIONAL,
    entity_refs: tuple[str, ...] = (),
    source_type: str = "test",
) -> SeerflowEvent:
    now_ns = 1_710_000_000_000_000_000
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=severity,
        message=message,
        source_type=source_type,
        source_id="test-source",
        entity_refs=entity_refs,
    )


class TestWriteBatch:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_single_event_persisted(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(message="hello world")
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 1
        finally:
            await backend.close()

    async def test_batch_write(self) -> None:
        backend = await self._make_backend()
        try:
            events = [_make_event(message=f"event {i}") for i in range(50)]
            await backend._write_batch(events)
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 50
        finally:
            await backend.close()

    async def test_event_id_stored_as_string(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event()
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT event_id FROM events")
            row = await cursor.fetchone()
            assert row[0] == str(event.event_id)
        finally:
            await backend.close()

    async def test_severity_stored_as_int(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(severity=SeverityLevel.CRITICAL)
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT severity_id FROM events")
            row = await cursor.fetchone()
            assert row[0] == 5
            assert isinstance(row[0], int)
        finally:
            await backend.close()

    async def test_entity_refs_stored_as_json(self) -> None:
        backend = await self._make_backend()
        try:
            refs = ("uuid-aaa", "uuid-bbb")
            event = _make_event(entity_refs=refs)
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT entity_refs FROM events")
            row = await cursor.fetchone()
            assert json.loads(row[0]) == ["uuid-aaa", "uuid-bbb"]
        finally:
            await backend.close()

    async def test_entity_events_junction_rows(self) -> None:
        backend = await self._make_backend()
        try:
            refs = ("uuid-aaa", "uuid-bbb")
            event = _make_event(entity_refs=refs)
            await backend._write_batch([event])
            cursor = await backend._conn.execute(
                "SELECT entity_uuid, event_id FROM entity_events ORDER BY entity_uuid"
            )
            rows = await cursor.fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "uuid-aaa"
            assert rows[1][0] == "uuid-bbb"
            assert rows[0][1] == str(event.event_id)
        finally:
            await backend.close()

    async def test_no_junction_rows_when_no_entity_refs(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(entity_refs=())
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM entity_events")
            row = await cursor.fetchone()
            assert row[0] == 0
        finally:
            await backend.close()

    async def test_msgpack_roundtrip(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(message="roundtrip test", severity=SeverityLevel.WARNING)
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT data FROM events")
            row = await cursor.fetchone()
            decoded = msgspec.msgpack.decode(row[0], type=SeerflowEvent)
            assert decoded.message == "roundtrip test"
            assert decoded.severity_id == SeverityLevel.WARNING
            assert decoded.event_id == event.event_id
        finally:
            await backend.close()

    async def test_empty_batch_is_noop(self) -> None:
        backend = await self._make_backend()
        try:
            await backend._write_batch([])
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 0
        finally:
            await backend.close()

    async def test_duplicate_event_id_ignored(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(message="original")
            await backend._write_batch([event])
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 1
        finally:
            await backend.close()

    async def test_fts_populated_on_insert(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event(message="authentication failed for user admin")
            await backend._write_batch([event])
            cursor = await backend._conn.execute(
                "SELECT message FROM events_fts WHERE events_fts MATCH 'authentication'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert "authentication" in row[0]
        finally:
            await backend.close()
