"""Unit tests for per-stage latency tracking in ``make_handler`` (S-080).

The handler now wraps the three major awaits — normalize / persist /
detect — with ``time.perf_counter_ns()`` brackets and records to a
``StageLatencyTracker`` when one is wired. The tracker stays ``None`` in
tests that do not opt in, so the existing behaviour is unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.api.latency import StageLatencyTracker
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent


def _ensemble_mock() -> MagicMock:
    ensemble = MagicMock()
    ensemble.process_event = MagicMock(
        return_value=MagicMock(
            score=0.0,
            is_anomaly=False,
            upper_threshold=1.0,
            anomaly_direction="up",
            source_type="syslog",
        )
    )
    return ensemble


def _storage_mock() -> MagicMock:
    storage = MagicMock()
    storage.write_alert = AsyncMock(return_value=True)
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_edge = AsyncMock()
    return storage


def _raw_event() -> RawEvent:
    return RawEvent(
        data=b"hello from 1.2.3.4",
        source_type="syslog",
        source_id="syslog-test",
        received_ns=1_700_000_000_000_000_000,
        metadata={},
    )


@pytest.mark.asyncio
async def test_handler_records_per_stage_latency_when_tracker_wired() -> None:
    tracker = StageLatencyTracker()
    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=_storage_mock(),
        latency_tracker=tracker,
    )

    await handler(_raw_event())

    snap = tracker.snapshot()
    # parse + storage + detect are the three instrumented hot stages.
    assert "parse" in snap
    assert "storage" in snap
    assert "detect" in snap
    for stage in ("parse", "storage", "detect"):
        assert snap[stage]["count"] >= 1.0


@pytest.mark.asyncio
async def test_handler_runs_without_tracker() -> None:
    """Existing call shape (no tracker kwarg) must keep working."""
    handler = make_handler(
        ensemble=_ensemble_mock(),
        storage=_storage_mock(),
    )
    # Should not raise; this is a smoke check.
    await handler(_raw_event())
