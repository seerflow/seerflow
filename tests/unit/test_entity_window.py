"""Tests for EntityWindowBuffer sliding window."""

from __future__ import annotations

import time
import uuid

from seerflow.correlation.window import EntityWindowBuffer
from seerflow.models.event import SeerflowEvent, SeverityLevel


def _make_event(
    *,
    entity_refs: tuple[str, ...] = (),
    timestamp_ns: int = 0,
    source_type: str = "syslog",
) -> SeerflowEvent:
    if timestamp_ns == 0:
        timestamp_ns = time.time_ns()
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns,
        severity_id=SeverityLevel.INFORMATIONAL,
        message="test",
        source_type=source_type,
        entity_refs=entity_refs,
    )


class TestEntityWindowBufferAddAndQuery:
    def test_add_event_stores_in_entity_window(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        event = _make_event(entity_refs=("uuid-a",))
        buf.add_event("uuid-a", event)
        results = buf.query("uuid-a")
        assert len(results) == 1
        assert results[0].event_id == event.event_id

    def test_query_unknown_entity_returns_empty(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        assert buf.query("nonexistent") == []

    def test_events_sorted_by_timestamp(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        now = time.time_ns()
        e1 = _make_event(timestamp_ns=now - 3000)
        e2 = _make_event(timestamp_ns=now - 5000)
        e3 = _make_event(timestamp_ns=now - 4000)
        buf.add_event("uuid-a", e1)
        buf.add_event("uuid-a", e2)
        buf.add_event("uuid-a", e3)
        results = buf.query("uuid-a")
        timestamps = [e.timestamp_ns for e in results]
        assert timestamps == [now - 5000, now - 4000, now - 3000]

    def test_max_events_per_entity_enforced(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=3)
        now = time.time_ns()
        for i in range(5):
            buf.add_event("uuid-a", _make_event(timestamp_ns=now - (5 - i) * 1000))
        results = buf.query("uuid-a")
        assert len(results) == 3

    def test_query_filters_by_time_range(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        now = time.time_ns()
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 3000))
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 2000))
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 1000))
        from seerflow.models.query import TimeRange

        results = buf.query(
            "uuid-a",
            time_range=TimeRange(start_ns=now - 2500, end_ns=now - 1500),
        )
        assert len(results) == 1
        assert results[0].timestamp_ns == now - 2000

    def test_query_filters_by_source_type(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        now = time.time_ns()
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 2000, source_type="syslog"))
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 1000, source_type="otlp"))
        results = buf.query("uuid-a", source_types=("syslog",))
        assert len(results) == 1
        assert results[0].source_type == "syslog"


class TestEntityWindowBufferExpiry:
    def test_expired_events_pruned_on_query(self) -> None:
        window_ns = 5_000_000_000  # 5 seconds
        buf = EntityWindowBuffer(window_ns=window_ns, max_events=100)
        now = time.time_ns()
        old = now - 10_000_000_000  # 10 sec ago
        buf.add_event("uuid-a", _make_event(timestamp_ns=old))
        buf.add_event("uuid-a", _make_event(timestamp_ns=now))
        results = buf.query("uuid-a")
        assert len(results) == 1

    def test_query_removes_fully_expired_entity(self) -> None:
        window_ns = 5_000_000_000
        buf = EntityWindowBuffer(window_ns=window_ns, max_events=100)
        old = time.time_ns() - 10_000_000_000
        buf.add_event("uuid-a", _make_event(timestamp_ns=old))
        assert buf.entity_count == 1
        results = buf.query("uuid-a")
        assert results == []
        assert buf.entity_count == 0

    def test_prune_removes_expired_events(self) -> None:
        window_ns = 5_000_000_000
        buf = EntityWindowBuffer(window_ns=window_ns, max_events=100)
        now = time.time_ns()
        old = now - 10_000_000_000
        buf.add_event("uuid-a", _make_event(timestamp_ns=old))
        buf.add_event("uuid-b", _make_event(timestamp_ns=now))
        buf.prune()
        assert buf.entity_count == 1  # uuid-a should be removed

    def test_stats_returns_entity_and_event_counts(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100)
        now = time.time_ns()
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 3000))
        buf.add_event("uuid-a", _make_event(timestamp_ns=now - 2000))
        buf.add_event("uuid-b", _make_event(timestamp_ns=now - 1000))
        stats = buf.stats()
        assert stats["entity_count"] == 2
        assert stats["total_events"] == 3


class TestEntityWindowLRU:
    def test_evicts_oldest_entity_when_max_exceeded(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100, max_entities=2)
        now = time.time_ns()
        buf.add_event("uuid-a", _make_event(timestamp_ns=now))
        buf.add_event("uuid-b", _make_event(timestamp_ns=now + 1000))
        buf.add_event("uuid-c", _make_event(timestamp_ns=now + 2000))
        # uuid-a should have been evicted
        assert buf.entity_count == 2
        assert buf.query("uuid-a") == []
        assert len(buf.query("uuid-b")) == 1
        assert len(buf.query("uuid-c")) == 1

    def test_no_eviction_when_under_limit(self) -> None:
        buf = EntityWindowBuffer(window_ns=60_000_000_000, max_events=100, max_entities=10)
        now = time.time_ns()
        buf.add_event("uuid-a", _make_event(timestamp_ns=now))
        buf.add_event("uuid-b", _make_event(timestamp_ns=now + 1000))
        assert buf.entity_count == 2
