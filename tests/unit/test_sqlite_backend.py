"""Tests for SqliteBackend — schema creation, event batch writes."""

from __future__ import annotations

import json
import time
import uuid

import aiosqlite
import msgspec
import pytest

from seerflow.api.constants import MAX_ALERT_SCAN
from seerflow.config import ConfigError, StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.storage.protocols import LogStore
from seerflow.storage.sqlite import (
    SqliteBackend,
    _build_query,
    _init_schema,
    _sanitize_fts_query,
    _validate_path,
)


class TestFtsSanitization:
    def test_normal_text_wrapped_in_quotes(self) -> None:
        assert _sanitize_fts_query("hello world") == '"hello world"'

    def test_double_quotes_stripped(self) -> None:
        assert _sanitize_fts_query('say "hello"') == '"say hello"'

    def test_control_characters_removed(self) -> None:
        assert _sanitize_fts_query("hello\x00world\x01test") == '"helloworldtest"'

    def test_length_capped_at_256(self) -> None:
        long_query = "a" * 300
        result = _sanitize_fts_query(long_query)
        assert len(result) == 258  # 256 chars + 2 quotes

    def test_empty_string_returns_empty_phrase(self) -> None:
        assert _sanitize_fts_query("") == '""'

    def test_whitespace_only_returns_empty_phrase(self) -> None:
        assert _sanitize_fts_query("   ") == '""'

    def test_single_quotes_stripped(self) -> None:
        assert _sanitize_fts_query("it's broken") == '"its broken"'

    def test_fts5_operators_neutralized(self) -> None:
        result = _sanitize_fts_query("error OR warning NOT info")
        assert result == '"error OR warning NOT info"'


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
            assert row[0] == SeverityLevel.CRITICAL.value
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

    async def test_template_id_sentinel_stored_as_null(self) -> None:
        backend = await self._make_backend()
        try:
            event = _make_event()  # template_id defaults to -1
            await backend._write_batch([event])
            cursor = await backend._conn.execute("SELECT template_id FROM events")
            row = await cursor.fetchone()
            assert row[0] is None  # -1 sentinel converted to NULL
        finally:
            await backend.close()


class TestWriteEvents:
    async def test_events_persisted_via_buffer_flush(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            events = [_make_event(message=f"event {i}") for i in range(5)]
            await backend.write_events(events)
            await backend.flush()
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 5
        finally:
            await backend.close()

    async def test_empty_write_is_noop(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            await backend.write_events([])
        finally:
            await backend.close()

    async def test_size_threshold_triggers_flush(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            events = [_make_event(message=f"event {i}") for i in range(1000)]
            await backend.write_events(events)
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 1000
        finally:
            await backend.close()

    async def test_events_persisted_after_manual_flush(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        events = [_make_event(message=f"event {i}") for i in range(5)]
        await backend.write_events(events)
        # Don't flush manually — close should flush
        # We need to check before close destroys the connection
        # So we flush + check, then close
        await backend.flush()
        cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        assert row[0] == 5
        await backend.close()


class TestSearchText:
    async def _make_backend_with_events(
        self, events: list[SeerflowEvent] | None = None
    ) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        if events is not None:
            await backend._write_batch(events)
        return backend

    async def test_finds_matching_events(self) -> None:
        e1 = _make_event(message="authentication failed for user admin")
        e2 = _make_event(message="connection established successfully")
        backend = await self._make_backend_with_events([e1, e2])
        try:
            results = await backend.search_text("authentication", 10)
            assert len(results) == 1
            assert results[0].message == "authentication failed for user admin"
        finally:
            await backend.close()

    async def test_no_matches_returns_empty(self) -> None:
        e1 = _make_event(message="hello world")
        backend = await self._make_backend_with_events([e1])
        try:
            results = await backend.search_text("nonexistent", 10)
            assert results == []
        finally:
            await backend.close()

    async def test_limit_respected(self) -> None:
        events = [_make_event(message=f"error on line {i}") for i in range(10)]
        backend = await self._make_backend_with_events(events)
        try:
            results = await backend.search_text("error", 3)
            assert len(results) == 3
        finally:
            await backend.close()

    async def test_empty_query_returns_empty(self) -> None:
        e1 = _make_event(message="hello world")
        backend = await self._make_backend_with_events([e1])
        try:
            results = await backend.search_text("", 10)
            assert results == []
        finally:
            await backend.close()

    async def test_operators_treated_as_literal(self) -> None:
        e1 = _make_event(message="error OR warning in log")
        backend = await self._make_backend_with_events([e1])
        try:
            results = await backend.search_text("error OR warning", 10)
            assert len(results) == 1
        finally:
            await backend.close()

    async def test_limit_clamped_to_ceiling(self) -> None:
        """Verify search_text clamps limit to internal ceiling."""
        e1 = _make_event(message="test event")
        backend = await self._make_backend_with_events([e1])
        try:
            results = await backend.search_text("test", 10_000_000)
            assert len(results) == 1
        finally:
            await backend.close()


class TestQueryEvents:
    async def _make_backend_with_events(
        self, events: list[SeerflowEvent] | None = None
    ) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        if events is not None:
            await backend._write_batch(events)
        return backend

    async def test_empty_result(self) -> None:
        backend = await self._make_backend_with_events()
        try:
            result = await backend.query_events(EventQuery())
            assert result.items == ()
            assert result.total == 0
            assert result.page == 1
        finally:
            await backend.close()

    async def test_returns_all_events_no_filter(self) -> None:
        events = [_make_event(message=f"event {i}") for i in range(3)]
        backend = await self._make_backend_with_events(events)
        try:
            result = await backend.query_events(EventQuery())
            assert result.total == 3
            assert len(result.items) == 3
        finally:
            await backend.close()

    async def test_filter_by_time_range(self) -> None:
        e_base = _make_event()
        e1 = msgspec.structs.replace(
            e_base, event_id=uuid.uuid4(), timestamp_ns=100, message="old"
        )
        e2 = msgspec.structs.replace(
            e_base, event_id=uuid.uuid4(), timestamp_ns=300, message="new"
        )
        backend = await self._make_backend_with_events([e1, e2])
        try:
            result = await backend.query_events(
                EventQuery(time_range=TimeRange(start_ns=200, end_ns=400))
            )
            assert result.total == 1
            assert result.items[0].message == "new"
        finally:
            await backend.close()

    async def test_filter_by_source_type(self) -> None:
        e1 = _make_event(source_type="syslog", message="sys event")
        e2 = _make_event(source_type="otlp", message="otlp event")
        backend = await self._make_backend_with_events([e1, e2])
        try:
            result = await backend.query_events(EventQuery(source_type="syslog"))
            assert result.total == 1
            assert result.items[0].message == "sys event"
        finally:
            await backend.close()

    async def test_filter_by_severity_min(self) -> None:
        e1 = _make_event(severity=SeverityLevel.INFORMATIONAL)
        e2 = _make_event(severity=SeverityLevel.CRITICAL)
        backend = await self._make_backend_with_events([e1, e2])
        try:
            result = await backend.query_events(EventQuery(severity_min=4))
            assert result.total == 1
            assert result.items[0].severity_id == SeverityLevel.CRITICAL
        finally:
            await backend.close()

    async def test_filter_by_entity_uuid(self) -> None:
        e1 = _make_event(entity_refs=("entity-aaa",), message="with entity")
        e2 = _make_event(entity_refs=(), message="no entity")
        backend = await self._make_backend_with_events([e1, e2])
        try:
            result = await backend.query_events(EventQuery(entity_uuid="entity-aaa"))
            assert result.total == 1
            assert result.items[0].message == "with entity"
        finally:
            await backend.close()

    async def test_pagination(self) -> None:
        events = [_make_event(message=f"event {i}") for i in range(5)]
        backend = await self._make_backend_with_events(events)
        try:
            page1 = await backend.query_events(EventQuery(limit=2, page=1))
            assert len(page1.items) == 2
            assert page1.total == 5
            assert page1.has_next is True

            page3 = await backend.query_events(EventQuery(limit=2, page=3))
            assert len(page3.items) == 1
            assert page3.has_next is False
        finally:
            await backend.close()

    async def test_events_sorted_desc(self) -> None:
        e_base = _make_event()
        e1 = msgspec.structs.replace(
            e_base, event_id=uuid.uuid4(), timestamp_ns=100, message="oldest"
        )
        e2 = msgspec.structs.replace(
            e_base, event_id=uuid.uuid4(), timestamp_ns=300, message="newest"
        )
        e3 = msgspec.structs.replace(
            e_base, event_id=uuid.uuid4(), timestamp_ns=200, message="middle"
        )
        backend = await self._make_backend_with_events([e1, e2, e3])
        try:
            result = await backend.query_events(EventQuery())
            messages = [e.message for e in result.items]
            assert messages == ["newest", "middle", "oldest"]
        finally:
            await backend.close()

    async def test_filter_by_text_query(self) -> None:
        e1 = _make_event(message="authentication failed for user admin")
        e2 = _make_event(message="connection established")
        backend = await self._make_backend_with_events([e1, e2])
        try:
            result = await backend.query_events(EventQuery(text_query="authentication"))
            assert result.total == 1
            assert result.items[0].message == "authentication failed for user admin"
        finally:
            await backend.close()


class TestBuildQuery:
    def test_no_filters(self) -> None:
        filters = EventQuery()
        where, joins, params = _build_query(filters)
        assert where == "1=1"
        assert joins == ""
        assert params == []

    def test_time_range(self) -> None:
        tr = TimeRange(start_ns=100, end_ns=200)
        filters = EventQuery(time_range=tr)
        where, _joins, params = _build_query(filters)
        assert "e.timestamp_ns >= ?" in where
        assert "e.timestamp_ns <= ?" in where
        assert params == [100, 200]

    def test_source_type(self) -> None:
        filters = EventQuery(source_type="syslog")
        where, _joins, params = _build_query(filters)
        assert "e.source_type = ?" in where
        assert params == ["syslog"]

    def test_severity_min(self) -> None:
        filters = EventQuery(severity_min=3)
        where, _joins, params = _build_query(filters)
        assert "e.severity_id >= ?" in where
        assert params == [3]

    def test_template_id(self) -> None:
        filters = EventQuery(template_id=42)
        where, _joins, params = _build_query(filters)
        assert "e.template_id = ?" in where
        assert params == [42]

    def test_entity_uuid_adds_join(self) -> None:
        filters = EventQuery(entity_uuid="uuid-123")
        where, joins, params = _build_query(filters)
        assert "JOIN entity_events" in joins
        assert "ee.entity_uuid = ?" in where
        assert params == ["uuid-123"]

    def test_text_query_adds_fts_join(self) -> None:
        filters = EventQuery(text_query="authentication failed")
        where, joins, params = _build_query(filters)
        assert "JOIN events_fts" in joins
        assert "events_fts MATCH ?" in where
        assert params == ['"authentication failed"']

    def test_compound_filters(self) -> None:
        tr = TimeRange(start_ns=100, end_ns=200)
        filters = EventQuery(time_range=tr, source_type="syslog", severity_min=3)
        where, _joins, params = _build_query(filters)
        assert " AND " in where
        assert len(params) == 4


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    alert_id: str = "",
    alert_type: str = "ml",
    message: str = "test alert",
    entity_uuid: str = "entity-aaa",
    dedup_key: str = "",
    severity: SeverityLevel = SeverityLevel.WARNING,
    timestamp_ns: int = 1_710_000_000_000_000_000,
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
) -> Alert:
    return Alert(
        alert_id=alert_id or str(uuid.uuid4()),
        alert_type=alert_type,
        timestamp_ns=timestamp_ns,
        severity_id=severity,
        rule_name="test-rule",
        description=message,
        entity_uuid=entity_uuid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=dedup_key or str(uuid.uuid4()),
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
    )


class TestWriteAlert:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_single_alert_persisted(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert()
            await backend.write_alert(alert)
            async with await backend._conn.execute("SELECT COUNT(*) FROM alerts") as cur:
                row = await cur.fetchone()
            assert row[0] == 1
        finally:
            await backend.close()

    async def test_alert_msgpack_roundtrip(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert(message="roundtrip", severity=SeverityLevel.CRITICAL)
            await backend.write_alert(alert)
            async with await backend._conn.execute("SELECT data FROM alerts") as cur:
                row = await cur.fetchone()
            decoded = msgspec.msgpack.decode(row[0], type=Alert)
            assert decoded.description == "roundtrip"
            assert decoded.severity_id == SeverityLevel.CRITICAL
        finally:
            await backend.close()

    async def test_severity_stored_as_int(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert(severity=SeverityLevel.CRITICAL)
            await backend.write_alert(alert)
            async with await backend._conn.execute("SELECT severity_id FROM alerts") as cur:
                row = await cur.fetchone()
            assert row[0] == SeverityLevel.CRITICAL.value
        finally:
            await backend.close()

    async def test_dedup_increments_count(self) -> None:
        backend = await self._make_backend()
        try:
            a1 = _make_alert(dedup_key="same-key", message="first")
            a2 = _make_alert(dedup_key="same-key", message="second")
            await backend.write_alert(a1)
            await backend.write_alert(a2)
            async with await backend._conn.execute(
                "SELECT dedup_count FROM alerts WHERE dedup_key = 'same-key'"
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == 2
        finally:
            await backend.close()

    async def test_dedup_updates_alert_id(self) -> None:
        backend = await self._make_backend()
        try:
            a1 = _make_alert(dedup_key="same-key")
            a2 = _make_alert(dedup_key="same-key")
            await backend.write_alert(a1)
            await backend.write_alert(a2)
            async with await backend._conn.execute(
                "SELECT alert_id, data FROM alerts WHERE dedup_key = 'same-key'"
            ) as cur:
                row = await cur.fetchone()
            decoded = msgspec.msgpack.decode(row[1], type=Alert)
            assert row[0] == decoded.alert_id  # column matches BLOB
        finally:
            await backend.close()

    async def test_dedup_updates_data_blob(self) -> None:
        backend = await self._make_backend()
        try:
            a1 = _make_alert(dedup_key="same-key", message="first")
            a2 = _make_alert(dedup_key="same-key", message="second")
            await backend.write_alert(a1)
            await backend.write_alert(a2)
            async with await backend._conn.execute(
                "SELECT data FROM alerts WHERE dedup_key = 'same-key'"
            ) as cur:
                row = await cur.fetchone()
            decoded = msgspec.msgpack.decode(row[0], type=Alert)
            assert decoded.description == "second"
        finally:
            await backend.close()


class TestWriteAlertJunctions:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_populates_junction_tables(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert(
                dedup_key="k1",
                mitre_tactics=("discovery",),
                mitre_techniques=("T1059.001",),
            )
            await backend.write_alert(alert)
            async with await backend._conn.execute(
                "SELECT tactic FROM alert_tactics WHERE dedup_key='k1'"
            ) as cur:
                rows = [r[0] for r in await cur.fetchall()]
            assert rows == ["discovery"]
            async with await backend._conn.execute(
                "SELECT technique FROM alert_techniques WHERE dedup_key='k1'"
            ) as cur:
                rows = [r[0] for r in await cur.fetchall()]
            assert rows == ["T1059.001"]
        finally:
            await backend.close()

    async def test_upsert_replaces_junction_rows(self) -> None:
        """Window-reset (outside dedup window) replaces junction rows."""
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            first = _make_alert(
                dedup_key="k1",
                timestamp_ns=base_ns,
                mitre_tactics=("discovery", "execution"),
                mitre_techniques=("T1059", "T1059.001"),
            )
            await backend.write_alert(first)
            # Outside the default 900s dedup window → window-reset path
            second = _make_alert(
                dedup_key="k1",
                alert_id="new-id",
                timestamp_ns=base_ns + 1_000_000_000_000,  # +1000s
                mitre_tactics=("execution",),
                mitre_techniques=("T1059.001",),
            )
            await backend.write_alert(second)
            async with await backend._conn.execute(
                "SELECT tactic FROM alert_tactics WHERE dedup_key='k1' ORDER BY tactic"
            ) as cur:
                tactics = [r[0] for r in await cur.fetchall()]
            async with await backend._conn.execute(
                "SELECT technique FROM alert_techniques WHERE dedup_key='k1'"
            ) as cur:
                techs = [r[0] for r in await cur.fetchall()]
            assert tactics == ["execution"]
            assert techs == ["T1059.001"]
        finally:
            await backend.close()

    async def test_dedup_bump_within_window_preserves_junction_rows(self) -> None:
        """Within-window dedup bump keeps the stored alert and its junction rows."""
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            first = _make_alert(
                dedup_key="k1",
                timestamp_ns=base_ns,
                mitre_tactics=("discovery",),
            )
            await backend.write_alert(first)
            # Dedup bump within window (default 900s) with EMPTY tactics
            second = _make_alert(
                dedup_key="k1",
                alert_id="new-id",
                timestamp_ns=base_ns + 60_000_000_000,  # +60s
                mitre_tactics=(),
            )
            await backend.write_alert(second)
            async with await backend._conn.execute(
                "SELECT tactic FROM alert_tactics WHERE dedup_key='k1'"
            ) as cur:
                tactics = [r[0] for r in await cur.fetchall()]
            # Original junction rows preserved because stored alert is unchanged
            assert tactics == ["discovery"]
        finally:
            await backend.close()


class TestDedupWindow:
    """Time-windowed dedup: within window increments count, outside resets."""

    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_within_window_increments_count(self) -> None:
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            gap_100s_ns = 100_000_000_000
            window_900s_ns = 900_000_000_000

            a1 = _make_alert(dedup_key="win-key", timestamp_ns=base_ns)
            a2 = _make_alert(dedup_key="win-key", timestamp_ns=base_ns + gap_100s_ns)
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            await backend.write_alert(a2, dedup_window_ns=window_900s_ns)

            async with await backend._conn.execute(
                "SELECT dedup_count FROM alerts WHERE dedup_key = 'win-key'"
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == 2
        finally:
            await backend.close()

    async def test_outside_window_resets_count(self) -> None:
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            gap_1000s_ns = 1_000_000_000_000
            window_900s_ns = 900_000_000_000

            a1 = _make_alert(dedup_key="out-key", timestamp_ns=base_ns)
            a2 = _make_alert(dedup_key="out-key", timestamp_ns=base_ns + gap_1000s_ns)
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            await backend.write_alert(a2, dedup_window_ns=window_900s_ns)

            async with await backend._conn.execute(
                "SELECT dedup_count FROM alerts WHERE dedup_key = 'out-key'"
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == 1
        finally:
            await backend.close()

    async def test_window_preserves_original_timestamp(self) -> None:
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            gap_100s_ns = 100_000_000_000
            window_900s_ns = 900_000_000_000

            a1 = _make_alert(dedup_key="ts-key", timestamp_ns=base_ns)
            a2 = _make_alert(dedup_key="ts-key", timestamp_ns=base_ns + gap_100s_ns)
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            await backend.write_alert(a2, dedup_window_ns=window_900s_ns)

            async with await backend._conn.execute(
                "SELECT timestamp_ns FROM alerts WHERE dedup_key = 'ts-key'"
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == base_ns
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_late_arriving_event_within_window_deduplicates(self) -> None:
        """Late-arriving alert (earlier timestamp) within window still deduplicates."""
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            gap_100s_ns = 100_000_000_000
            window_900s_ns = 900_000_000_000

            a1 = _make_alert(dedup_key="late-key", timestamp_ns=base_ns + gap_100s_ns)
            a2 = _make_alert(dedup_key="late-key", timestamp_ns=base_ns)  # earlier!
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            await backend.write_alert(a2, dedup_window_ns=window_900s_ns)

            page = await backend.query_alerts(AlertQuery())
            deduped = [a for a in page.items if a.dedup_key == "late-key"]
            assert len(deduped) == 1
            assert deduped[0].dedup_count == 2
        finally:
            await backend.close()


class TestQueryAlerts:
    async def _make_backend_with_alerts(self, alerts: list[Alert] | None = None) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        if alerts is not None:
            for alert in alerts:
                await backend.write_alert(alert)
        return backend

    async def test_empty_result(self) -> None:
        backend = await self._make_backend_with_alerts()
        try:
            result = await backend.query_alerts(AlertQuery())
            assert result.items == ()
            assert result.total == 0
        finally:
            await backend.close()

    async def test_returns_all_alerts(self) -> None:
        alerts = [_make_alert(message=f"alert {i}") for i in range(3)]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            result = await backend.query_alerts(AlertQuery())
            assert result.total == 3
        finally:
            await backend.close()

    async def test_filter_by_time_range(self) -> None:
        a1 = _make_alert()  # timestamp_ns = 1_710_000_000_000_000_000
        backend = await self._make_backend_with_alerts([a1])
        try:
            tr = TimeRange(start_ns=1_700_000_000_000_000_000, end_ns=1_720_000_000_000_000_000)
            result = await backend.query_alerts(AlertQuery(time_range=tr))
            assert result.total == 1

            tr_miss = TimeRange(start_ns=1, end_ns=2)
            result2 = await backend.query_alerts(AlertQuery(time_range=tr_miss))
            assert result2.total == 0
        finally:
            await backend.close()

    async def test_filter_by_alert_type(self) -> None:
        a1 = _make_alert(alert_type="ml")
        a2 = _make_alert(alert_type="sigma")
        backend = await self._make_backend_with_alerts([a1, a2])
        try:
            result = await backend.query_alerts(AlertQuery(alert_type="sigma"))
            assert result.total == 1
            assert result.items[0].alert_type == "sigma"
        finally:
            await backend.close()

    async def test_filter_by_severity_min(self) -> None:
        a1 = _make_alert(severity=SeverityLevel.INFORMATIONAL)
        a2 = _make_alert(severity=SeverityLevel.CRITICAL)
        backend = await self._make_backend_with_alerts([a1, a2])
        try:
            result = await backend.query_alerts(AlertQuery(severity_min=4))
            assert result.total == 1
        finally:
            await backend.close()

    async def test_filter_by_entity_uuid(self) -> None:
        a1 = _make_alert(entity_uuid="entity-aaa")
        a2 = _make_alert(entity_uuid="entity-bbb")
        backend = await self._make_backend_with_alerts([a1, a2])
        try:
            result = await backend.query_alerts(AlertQuery(entity_uuid="entity-aaa"))
            assert result.total == 1
        finally:
            await backend.close()

    async def test_pagination(self) -> None:
        alerts = [_make_alert(message=f"alert {i}") for i in range(5)]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page1 = await backend.query_alerts(AlertQuery(limit=2, page=1))
            assert len(page1.items) == 2
            assert page1.total == 5
            assert page1.has_next is True
        finally:
            await backend.close()


def _make_mitre_alert(
    *,
    alert_id: str,
    ts_ns: int,
    tactics: tuple[str, ...] = (),
    techniques: tuple[str, ...] = (),
    dedup_key: str | None = None,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="sigma",
        timestamp_ns=ts_ns,
        severity_id=SeverityLevel.WARNING,
        rule_name="test",
        description="",
        entity_uuid="e1",
        entity_value="1.2.3.4",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=tactics,
        mitre_techniques=techniques,
        dedup_key=dedup_key or f"test:{alert_id}",
    )


class TestQueryAlertsMitreFilter:
    async def _make_backend_with_alerts(self, alerts: list[Alert] | None = None) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        if alerts is not None:
            for alert in alerts:
                await backend.write_alert(alert)
        return backend

    async def test_filter_by_tactic_present(self) -> None:
        alerts = [
            _make_mitre_alert(
                alert_id="a1", ts_ns=1_000, tactics=("discovery",), techniques=("t1033",)
            ),
            _make_mitre_alert(
                alert_id="a2", ts_ns=2_000, tactics=("execution",), techniques=("t1059",)
            ),
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page = await backend.query_alerts(AlertQuery(tactic="discovery"))
            assert page.total == 1
            assert [a.alert_id for a in page.items] == ["a1"]
        finally:
            await backend.close()

    async def test_filter_by_tactic_absent(self) -> None:
        alerts = [
            _make_mitre_alert(
                alert_id="a1", ts_ns=1_000, tactics=("discovery",), techniques=("t1033",)
            ),
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page = await backend.query_alerts(AlertQuery(tactic="nonexistent"))
            assert page.total == 0
            assert page.items == ()
        finally:
            await backend.close()

    async def test_filter_by_technique_case_insensitive(self) -> None:
        alerts = [
            _make_mitre_alert(
                alert_id="a1", ts_ns=1_000, tactics=("discovery",), techniques=("t1033",)
            ),
            _make_mitre_alert(
                alert_id="a2", ts_ns=2_000, tactics=("execution",), techniques=("t1059",)
            ),
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page = await backend.query_alerts(AlertQuery(technique="T1033"))
            assert page.total == 1
            assert page.items[0].alert_id == "a1"
        finally:
            await backend.close()

    async def test_filter_by_tactic_and_technique(self) -> None:
        alerts = [
            _make_mitre_alert(
                alert_id="a1", ts_ns=1_000, tactics=("discovery",), techniques=("t1033",)
            ),
            _make_mitre_alert(
                alert_id="a2", ts_ns=2_000, tactics=("discovery",), techniques=("t1087",)
            ),
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page = await backend.query_alerts(AlertQuery(tactic="discovery", technique="T1033"))
            assert page.total == 1
            assert page.items[0].alert_id == "a1"
        finally:
            await backend.close()

    async def test_pagination_under_filter_preserves_total(self) -> None:
        backend = await self._make_backend_with_alerts()
        try:
            for i in range(MAX_ALERT_SCAN + 50):
                await backend.write_alert(
                    _make_mitre_alert(
                        alert_id=f"a{i}",
                        ts_ns=1_000 + i,
                        tactics=("discovery",),
                        techniques=("t1033",),
                        dedup_key=f"test:a{i}",
                    )
                )
            page = await backend.query_alerts(AlertQuery(tactic="discovery", page=1, limit=50))
            assert page.total == MAX_ALERT_SCAN + 50
            assert len(page.items) == 50
        finally:
            await backend.close()

    async def test_technique_filter_case_insensitive_sql(self) -> None:
        backend = await self._make_backend_with_alerts(
            [
                _make_mitre_alert(
                    alert_id="k1",
                    ts_ns=1_000,
                    tactics=("discovery",),
                    techniques=("T1059.001",),
                    dedup_key="k1",
                ),
            ]
        )
        try:
            page = await backend.query_alerts(AlertQuery(technique="t1059.001", page=1, limit=10))
            assert page.total == 1
        finally:
            await backend.close()

    async def test_unfiltered_and_tactic_filter_agree_on_overlap(self) -> None:
        """Unfiltered query and ``tactic="discovery"`` must agree on the
        discovery-tagged subset. Locks in the invariant that both paths
        return consistent data now that both are SQL-level.
        """
        alerts = [
            _make_mitre_alert(
                alert_id=f"a{i}",
                ts_ns=10_000 + i,
                tactics=("discovery",) if i % 2 == 0 else ("execution",),
                techniques=("t1033",) if i % 2 == 0 else ("t1059",),
                dedup_key=f"test:fs:a{i}",
            )
            for i in range(6)
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            unfiltered = await backend.query_alerts(AlertQuery(limit=100))
            filtered = await backend.query_alerts(AlertQuery(tactic="discovery", limit=100))
            assert unfiltered.total == 6
            assert filtered.total == 3
            unfiltered_discovery_ids = {
                a.alert_id for a in unfiltered.items if "discovery" in a.mitre_tactics
            }
            filtered_ids = {a.alert_id for a in filtered.items}
            assert unfiltered_discovery_ids == filtered_ids
        finally:
            await backend.close()

    async def test_tactic_filter_is_case_sensitive_by_contract(self) -> None:
        """Plan decision 2: tactics are a canonical snake_case enum and
        the filter is case-sensitive. This test locks in the semantics
        — non-canonical values written to the store (e.g. via a
        misbehaving rule writer) are NOT matched and drop silently.
        """
        alerts = [
            _make_mitre_alert(
                alert_id="canonical",
                ts_ns=1_000,
                tactics=("discovery",),
                techniques=("t1033",),
            ),
            _make_mitre_alert(
                alert_id="uppercase",
                ts_ns=2_000,
                tactics=("Discovery",),
                techniques=("t1033",),
            ),
        ]
        backend = await self._make_backend_with_alerts(alerts)
        try:
            page = await backend.query_alerts(AlertQuery(tactic="discovery"))
            assert page.total == 1
            assert [a.alert_id for a in page.items] == ["canonical"]
        finally:
            await backend.close()


class TestUpdateFeedback:
    async def _make_backend_with_alert(self, alert: Alert) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        await backend.write_alert(alert)
        return backend

    async def test_update_feedback_tp(self) -> None:
        alert = _make_alert()
        backend = await self._make_backend_with_alert(alert)
        try:
            await backend.update_feedback(alert.alert_id, "tp")
            async with await backend._conn.execute(
                "SELECT feedback FROM alerts WHERE alert_id = ?", [alert.alert_id]
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == "tp"
        finally:
            await backend.close()

    async def test_update_feedback_fp(self) -> None:
        alert = _make_alert()
        backend = await self._make_backend_with_alert(alert)
        try:
            await backend.update_feedback(alert.alert_id, "fp")
            async with await backend._conn.execute(
                "SELECT feedback FROM alerts WHERE alert_id = ?", [alert.alert_id]
            ) as cur:
                row = await cur.fetchone()
            assert row[0] == "fp"
        finally:
            await backend.close()

    async def test_feedback_updates_data_blob(self) -> None:
        alert = _make_alert()
        backend = await self._make_backend_with_alert(alert)
        try:
            await backend.update_feedback(alert.alert_id, "tp")
            async with await backend._conn.execute(
                "SELECT data FROM alerts WHERE alert_id = ?", [alert.alert_id]
            ) as cur:
                row = await cur.fetchone()
            decoded = msgspec.msgpack.decode(row[0], type=Alert)
            assert decoded.feedback == "tp"
        finally:
            await backend.close()

    async def test_nonexistent_alert_is_noop(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            await backend.update_feedback("nonexistent-id", "tp")
        finally:
            await backend.close()


class TestModelStore:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_save_and_load(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.save_state("hst:global", b"model-data-bytes")
            result = await backend.load_state("hst:global")
            assert result == b"model-data-bytes"
        finally:
            await backend.close()

    async def test_load_nonexistent_returns_none(self) -> None:
        backend = await self._make_backend()
        try:
            result = await backend.load_state("nonexistent-key")
            assert result is None
        finally:
            await backend.close()

    async def test_save_overwrites_existing(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.save_state("hst:global", b"v1")
            await backend.save_state("hst:global", b"v2")
            result = await backend.load_state("hst:global")
            assert result == b"v2"
        finally:
            await backend.close()

    async def test_save_empty_key_rejected(self) -> None:
        backend = await self._make_backend()
        try:
            with pytest.raises(ValueError, match="empty"):
                await backend.save_state("", b"data")
        finally:
            await backend.close()

    async def test_save_long_key_rejected(self) -> None:
        backend = await self._make_backend()
        try:
            with pytest.raises(ValueError, match="exceeds"):
                await backend.save_state("a" * 257, b"data")
        finally:
            await backend.close()

    async def test_load_empty_key_rejected(self) -> None:
        backend = await self._make_backend()
        try:
            with pytest.raises(ValueError, match="empty"):
                await backend.load_state("")
        finally:
            await backend.close()

    async def test_updated_at_set(self) -> None:
        backend = await self._make_backend()
        try:
            before_ns = time.time_ns()
            await backend.save_state("key", b"data")
            after_ns = time.time_ns()
            async with await backend._conn.execute(
                "SELECT updated_at FROM model_state WHERE key = ?", ["key"]
            ) as cur:
                row = await cur.fetchone()
            assert before_ns <= row[0] <= after_ns
        finally:
            await backend.close()

    async def test_delete_state_removes_existing_key(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.save_state("k", b"body")
            await backend.delete_state("k")
            assert await backend.load_state("k") is None
        finally:
            await backend.close()

    async def test_delete_state_noop_on_missing_key(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.delete_state("never_saved")
            assert await backend.load_state("never_saved") is None
        finally:
            await backend.close()

    async def test_delete_state_idempotent(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.save_state("k", b"body")
            await backend.delete_state("k")
            await backend.delete_state("k")
            assert await backend.load_state("k") is None
        finally:
            await backend.close()

    async def test_delete_state_rejects_empty_key(self) -> None:
        backend = await self._make_backend()
        try:
            with pytest.raises(ValueError, match="empty"):
                await backend.delete_state("")
        finally:
            await backend.close()

    async def test_delete_state_rejects_long_key(self) -> None:
        backend = await self._make_backend()
        try:
            with pytest.raises(ValueError, match="exceeds"):
                await backend.delete_state("a" * 257)
        finally:
            await backend.close()


class TestProtocolConformance:
    async def test_isinstance_alert_store(self) -> None:
        from seerflow.storage.protocols import AlertStore

        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            assert isinstance(backend, AlertStore)
        finally:
            await backend.close()

    async def test_isinstance_model_store(self) -> None:
        from seerflow.storage.protocols import ModelStore as ModelStoreProto

        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            assert isinstance(backend, ModelStoreProto)
        finally:
            await backend.close()


class TestTemplateTable:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_write_templates_creates_records(self) -> None:
        from seerflow.storage.sqlite import TemplateInfo

        backend = await self._make_backend()
        try:
            templates = [
                TemplateInfo(
                    template_id=1,
                    template_str="Login from <*>",
                    first_seen_ns=1000,
                    last_seen_ns=2000,
                    event_count=5,
                    example_message="Login from 10.0.1.1",
                ),
            ]
            await backend.write_templates(templates)
            result = await backend.get_templates()
            assert len(result) == 1
            assert result[0].template_id == 1
            assert result[0].event_count == 5
            assert result[0].template_str == "Login from <*>"
            assert result[0].example_message == "Login from 10.0.1.1"
        finally:
            await backend.close()

    async def test_write_templates_upsert_increments(self) -> None:
        from seerflow.storage.sqlite import TemplateInfo

        backend = await self._make_backend()
        try:
            t1 = TemplateInfo(
                template_id=1,
                template_str="Login from <*>",
                first_seen_ns=1000,
                last_seen_ns=2000,
                event_count=3,
                example_message="Login from 10.0.1.1",
            )
            await backend.write_templates([t1])
            t2 = TemplateInfo(
                template_id=1,
                template_str="Login from <*>",
                first_seen_ns=3000,
                last_seen_ns=4000,
                event_count=2,
                example_message="Login from 10.0.1.2",
            )
            await backend.write_templates([t2])
            result = await backend.get_templates()
            assert result[0].event_count == 5  # 3 + 2
            assert result[0].last_seen_ns == 4000
            assert result[0].example_message == "Login from 10.0.1.1"  # preserved
            assert result[0].first_seen_ns == 1000  # preserved
        finally:
            await backend.close()

    async def test_write_templates_empty_is_noop(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.write_templates([])
            result = await backend.get_templates()
            assert len(result) == 0
        finally:
            await backend.close()

    async def test_get_templates_sorted_by_count(self) -> None:
        from seerflow.storage.sqlite import TemplateInfo

        backend = await self._make_backend()
        try:
            templates = [
                TemplateInfo(
                    template_id=1,
                    template_str="A",
                    first_seen_ns=1,
                    last_seen_ns=1,
                    event_count=10,
                    example_message="a",
                ),
                TemplateInfo(
                    template_id=2,
                    template_str="B",
                    first_seen_ns=1,
                    last_seen_ns=1,
                    event_count=50,
                    example_message="b",
                ),
                TemplateInfo(
                    template_id=3,
                    template_str="C",
                    first_seen_ns=1,
                    last_seen_ns=1,
                    event_count=1,
                    example_message="c",
                ),
            ]
            await backend.write_templates(templates)
            result = await backend.get_templates()
            assert [t.template_id for t in result] == [2, 1, 3]
        finally:
            await backend.close()


class TestFlush:
    @pytest.mark.asyncio
    async def test_flush_empty_buffer_does_not_raise(self) -> None:
        """flush() on an empty buffer completes without error."""
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            assert hasattr(backend, "flush")
            await backend.flush()  # Should not raise even when buffer is empty
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_flush_writes_pending_events(self) -> None:
        """Public flush() drains the write buffer and persists events."""
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            events = [_make_event(message=f"flush-test {i}") for i in range(3)]
            await backend.write_events(events)
            await backend.flush()
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 3
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_flush_idempotent(self) -> None:
        """Calling flush() twice does not duplicate events."""
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            events = [_make_event(message=f"idem {i}") for i in range(2)]
            await backend.write_events(events)
            await backend.flush()
            await backend.flush()  # second flush on empty buffer — safe
            cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            assert row[0] == 2
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_flush_after_close_does_not_raise(self) -> None:
        """flush() on an already-closed backend must not raise."""
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        await backend.close()
        await backend.flush()  # Must not raise ProgrammingError


class TestFeedbackStorage:
    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_get_alert_by_id_returns_alert(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert(alert_id="test-123")
            await backend.write_alert(alert, dedup_window_ns=0)
            result = await backend.get_alert_by_id("test-123")
            assert result is not None
            assert result.alert_id == "test-123"
        finally:
            await backend.close()

    async def test_get_alert_by_id_returns_none_for_missing(self) -> None:
        backend = await self._make_backend()
        try:
            result = await backend.get_alert_by_id("nonexistent")
            assert result is None
        finally:
            await backend.close()

    async def test_get_feedback_stats_empty(self) -> None:
        backend = await self._make_backend()
        try:
            stats = await backend.get_feedback_stats()
            assert stats == {"tp": 0, "fp": 0, "total": 0}
        finally:
            await backend.close()

    async def test_get_feedback_stats_with_data(self) -> None:
        backend = await self._make_backend()
        try:
            alert1 = _make_alert(alert_id="a1")
            alert2 = _make_alert(alert_id="a2")
            alert3 = _make_alert(alert_id="a3")
            await backend.write_alert(alert1, dedup_window_ns=0)
            await backend.write_alert(alert2, dedup_window_ns=0)
            await backend.write_alert(alert3, dedup_window_ns=0)
            await backend.update_feedback("a1", "tp")
            await backend.update_feedback("a2", "fp")
            await backend.update_feedback("a3", "tp")
            stats = await backend.get_feedback_stats()
            assert stats == {"tp": 2, "fp": 1, "total": 3}
        finally:
            await backend.close()


class TestWriteAlertDedupReturn:
    """write_alert() return value: True on new insert, False on dedup bump."""

    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_new_insert_returns_true(self) -> None:
        backend = await self._make_backend()
        try:
            alert = _make_alert(dedup_key="fresh-key")
            result = await backend.write_alert(alert)
            assert result is True
        finally:
            await backend.close()

    async def test_dedup_bump_returns_false(self) -> None:
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            window_900s_ns = 900_000_000_000
            a1 = _make_alert(dedup_key="dedup-key", timestamp_ns=base_ns)
            a2 = _make_alert(dedup_key="dedup-key", timestamp_ns=base_ns + 100_000_000_000)
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            result = await backend.write_alert(a2, dedup_window_ns=window_900s_ns)
            assert result is False
        finally:
            await backend.close()

    async def test_window_reset_returns_true(self) -> None:
        backend = await self._make_backend()
        try:
            base_ns = 1_710_000_000_000_000_000
            window_900s_ns = 900_000_000_000
            gap_1000s_ns = 1_000_000_000_000
            a1 = _make_alert(dedup_key="reset-key", timestamp_ns=base_ns)
            a2 = _make_alert(dedup_key="reset-key", timestamp_ns=base_ns + gap_1000s_ns)
            await backend.write_alert(a1, dedup_window_ns=window_900s_ns)
            result = await backend.write_alert(a2, dedup_window_ns=window_900s_ns)
            assert result is True
        finally:
            await backend.close()


class TestCountBySeverity:
    """Tests for SqliteBackend.count_by_severity."""

    async def _make_backend(self) -> SqliteBackend:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        return await SqliteBackend.connect(config)

    async def test_empty_returns_empty_dict(self) -> None:
        backend = await self._make_backend()
        try:
            counts = await backend.count_by_severity()
            assert counts == {}
        finally:
            await backend.close()

    async def test_mixed_severities(self) -> None:
        backend = await self._make_backend()
        try:
            for i in range(3):
                await backend.write_alert(
                    _make_alert(alert_id=f"a{i}", severity=SeverityLevel.ERROR)
                )
            for i in range(2):
                await backend.write_alert(
                    _make_alert(alert_id=f"b{i}", severity=SeverityLevel.CRITICAL)
                )
            await backend.write_alert(_make_alert(alert_id="c0", severity=SeverityLevel.WARNING))

            counts = await backend.count_by_severity()
            assert counts == {"error": 3, "critical": 2, "warning": 1}
        finally:
            await backend.close()

    async def test_unknown_severity_bucketed(self) -> None:
        backend = await self._make_backend()
        try:
            await backend.write_alert(_make_alert(alert_id="a0", severity=SeverityLevel.ERROR))
            # Poison a row with an out-of-range severity_id to simulate dirty data.
            await backend._conn.execute("UPDATE alerts SET severity_id = 99 WHERE alert_id = 'a0'")
            await backend._conn.commit()
            # Insert a second known-severity alert so both buckets are present.
            await backend.write_alert(_make_alert(alert_id="b0", severity=SeverityLevel.ERROR))

            counts = await backend.count_by_severity()
            assert counts.get("error") == 1
            assert counts.get("unknown") == 1
        finally:
            await backend.close()


def test_sqlite_backend_has_no_dict():
    """Guard: SqliteBackend + mixin MUST preserve __slots__.

    Skip __init__ to isolate the slot-discipline check from constructor
    behavior. If any class in the MRO forgets ``__slots__ = ()``, the
    resulting instance gains a ``__dict__`` regardless of __init__.
    """
    from seerflow.storage.sqlite import SqliteBackend

    backend = object.__new__(SqliteBackend)
    assert not hasattr(backend, "__dict__"), (
        "SqliteBackend gained a __dict__ — a mixin in the MRO is missing __slots__ = ()"
    )
