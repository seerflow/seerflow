"""Tests for entity timeline queries."""

from __future__ import annotations

import uuid

import pytest

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import TimeRange


def _make_event(
    *,
    entity_refs: tuple[str, ...] = (),
    related_ips: tuple[str, ...] = (),
    timestamp_ns: int = 1_700_000_000_000_000_000,
    source_type: str = "syslog",
    severity_id: SeverityLevel = SeverityLevel.INFORMATIONAL,
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns,
        severity_id=severity_id,
        message="test event",
        source_type=source_type,
        entity_refs=entity_refs,
        related_ips=related_ips,
    )


class TestGetTimeline:
    @pytest.fixture
    async def backend(self, tmp_path):
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        b = await SqliteBackend.connect(config)
        yield b
        await b.close()

    async def test_returns_events_for_entity(self, backend) -> None:
        entity_uuid = "test-entity-uuid"
        e1 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=1000)
        e2 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=2000)
        e3 = _make_event(entity_refs=("other-uuid",), timestamp_ns=1500)
        await backend.write_events([e1, e2, e3])
        await backend._write_buffer.flush()

        time_range = TimeRange(start_ns=0, end_ns=3000)
        results = await backend.get_timeline(entity_uuid, time_range)
        assert len(results) == 2
        assert all(entity_uuid in e.entity_refs for e in results)

    async def test_sorted_by_timestamp_ascending(self, backend) -> None:
        entity_uuid = "test-entity-uuid"
        e1 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=3000)
        e2 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=1000)
        e3 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=2000)
        await backend.write_events([e1, e2, e3])
        await backend._write_buffer.flush()

        time_range = TimeRange(start_ns=0, end_ns=5000)
        results = await backend.get_timeline(entity_uuid, time_range)
        timestamps = [e.timestamp_ns for e in results]
        assert timestamps == sorted(timestamps)

    async def test_filtered_by_time_range(self, backend) -> None:
        entity_uuid = "test-entity-uuid"
        e1 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=1000)
        e2 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=2000)
        e3 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=3000)
        await backend.write_events([e1, e2, e3])
        await backend._write_buffer.flush()

        time_range = TimeRange(start_ns=1500, end_ns=2500)
        results = await backend.get_timeline(entity_uuid, time_range)
        assert len(results) == 1
        assert results[0].timestamp_ns == 2000

    async def test_empty_result_for_unknown_entity(self, backend) -> None:
        time_range = TimeRange(start_ns=0, end_ns=999_999_999_999)
        results = await backend.get_timeline("nonexistent-uuid", time_range)
        assert results == []

    async def test_filterable_by_source_type(self, backend) -> None:
        entity_uuid = "test-entity-uuid"
        e1 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=1000, source_type="syslog")
        e2 = _make_event(entity_refs=(entity_uuid,), timestamp_ns=2000, source_type="otlp")
        await backend.write_events([e1, e2])
        await backend._write_buffer.flush()

        time_range = TimeRange(start_ns=0, end_ns=5000)
        results = await backend.get_timeline(
            entity_uuid,
            time_range,
            source_type="syslog",
        )
        assert len(results) == 1
        assert results[0].source_type == "syslog"
