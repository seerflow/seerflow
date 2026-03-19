"""Tests for SqliteBackend — schema creation, event batch writes."""

from __future__ import annotations

import json
import time
import uuid

import aiosqlite
import msgspec
import pytest

from seerflow.config import ConfigError, StorageConfig
from seerflow.models.alert import Alert, FeedbackType
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
            assert backend._write_buffer is not None
            await backend._write_buffer.flush()
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
        assert backend._write_buffer is not None
        await backend._write_buffer.flush()
        cursor = await backend._conn.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        assert row[0] == 5
        await backend.close()


class TestWritePerformance:
    async def test_batch_write_throughput(self) -> None:
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            events = [_make_event(message=f"perf event {i}") for i in range(10_000)]
            start = time.perf_counter()
            await backend._write_batch(events)
            elapsed = time.perf_counter() - start
            rate = 10_000 / elapsed
            assert rate >= 1000, f"Write throughput {rate:.0f}/sec below 1000/sec floor"
        finally:
            await backend.close()


class TestQueryPerformance:
    async def test_query_100k_events_under_5s(self) -> None:
        """Query 100K events — informational benchmark."""
        config = StorageConfig(backend="sqlite", sqlite_path=":memory:")
        backend = await SqliteBackend.connect(config)
        try:
            for batch_start in range(0, 100_000, 10_000):
                events = [_make_event(message=f"event {batch_start + i}") for i in range(10_000)]
                await backend._write_batch(events)

            start = time.perf_counter()
            result = await backend.query_events(EventQuery(limit=100))
            elapsed = time.perf_counter() - start

            assert result.total == 100_000
            assert len(result.items) == 100
            assert elapsed < 5.0, f"Query took {elapsed:.2f}s — expected <5s"
        finally:
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
    alert_type: str = "ml",
    message: str = "test alert",
    entity_uuid: str = "entity-aaa",
    dedup_key: str = "",
    severity: SeverityLevel = SeverityLevel.WARNING,
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type=alert_type,
        timestamp_ns=1_710_000_000_000_000_000,
        severity_id=severity,
        rule_name="test-rule",
        description=message,
        entity_uuid=entity_uuid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=dedup_key or str(uuid.uuid4()),
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


class TestQueryAlerts:
    async def _make_backend_with_alerts(
        self, alerts: list[Alert] | None = None
    ) -> SqliteBackend:
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
