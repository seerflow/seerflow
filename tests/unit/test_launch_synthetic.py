"""Unit tests for the deterministic launch-kit event generator (S-090)."""

from __future__ import annotations

from seerflow.launch.synthetic import build_events
from seerflow.receivers.base import RawEvent


def test_build_events_count() -> None:
    events = build_events(25)
    assert len(events) == 25
    assert all(isinstance(e, RawEvent) for e in events)


def test_build_events_is_rawevent_syslog() -> None:
    (event,) = build_events(1)
    assert event.source_type == "syslog"
    assert isinstance(event.data, bytes)
    assert event.received_ns > 0


def test_build_events_deterministic_for_seed() -> None:
    a = build_events(40, seed=99)
    b = build_events(40, seed=99)
    assert [e.data for e in a] == [e.data for e in b]


def test_build_events_seed_changes_payload() -> None:
    a = build_events(40, seed=1)
    b = build_events(40, seed=2)
    assert [e.data for e in a] != [e.data for e in b]


def test_build_events_zero() -> None:
    assert build_events(0) == []
