"""S-082 unit tests for ``EntityWindowBuffer`` bounds reporting."""

from __future__ import annotations

import time
import uuid

import pytest

from seerflow.correlation.window import EntityWindowBuffer
from seerflow.models.event import SeerflowEvent


def _make_event(timestamp_ns: int | None = None) -> SeerflowEvent:
    """Tiny event factory carrying only the fields the buffer reads."""
    now = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=now,
        observed_ns=now,
        source_type="syslog",
        message="test",
    )


@pytest.mark.unit
def test_fresh_buffer_bounds_zero_current() -> None:
    buf = EntityWindowBuffer(window_ns=10**9, max_events=100, max_entities=5)
    bounds = buf.bounds()
    assert bounds == {"current": 0, "max": 5, "evictions": 0}


@pytest.mark.unit
def test_eviction_counter_increments_on_lru_overflow() -> None:
    buf = EntityWindowBuffer(window_ns=10**12, max_events=10, max_entities=3)
    for i in range(8):
        buf.add_event(f"entity-{i}", _make_event())

    # Capacity holds and the 5 overflow inserts each trigger an LRU pop.
    bounds = buf.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 5


@pytest.mark.unit
def test_eviction_counter_does_not_increment_for_existing_entity() -> None:
    buf = EntityWindowBuffer(window_ns=10**12, max_events=10, max_entities=3)
    buf.add_event("alice", _make_event())
    buf.add_event("alice", _make_event())  # promotes, no eviction
    buf.add_event("alice", _make_event())

    assert buf.bounds()["evictions"] == 0
