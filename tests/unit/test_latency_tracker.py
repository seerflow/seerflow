"""Unit tests for :mod:`seerflow.api.latency` (S-080).

The ``StageLatencyTracker`` is a thread-safe ring buffer keyed by stage name.
It feeds the comprehensive ``/api/v1/health`` envelope with rolling
``p50/p95/p99`` per pipeline stage, capped so health probes stay under the
50 ms budget mandated by FR-047.
"""

from __future__ import annotations

import logging
import statistics
import threading

import pytest

from seerflow.api.latency import StageLatencyTracker


class TestStageLatencyTracker:
    """Behaviour of the rolling per-stage latency reservoir."""

    def test_empty_snapshot_returns_empty_dict(self) -> None:
        tracker = StageLatencyTracker()
        assert tracker.snapshot() == {}

    def test_records_and_returns_percentiles(self) -> None:
        tracker = StageLatencyTracker()
        samples = [float(i) for i in range(1, 1001)]  # 1..1000
        for s in samples:
            tracker.record("parse", s)

        snap = tracker.snapshot()
        assert "parse" in snap
        bucket = snap["parse"]
        assert bucket["count"] == 1000

        # statistics.quantiles(n=100) returns 99 cutpoints; index 49 -> p50,
        # 94 -> p95, 98 -> p99 (zero-based) using "inclusive" method.
        expected_cuts = statistics.quantiles(samples, n=100, method="inclusive")
        assert bucket["p50"] == pytest.approx(expected_cuts[49])
        assert bucket["p95"] == pytest.approx(expected_cuts[94])
        assert bucket["p99"] == pytest.approx(expected_cuts[98])

    def test_per_stage_isolation(self) -> None:
        tracker = StageLatencyTracker()
        for v in (10.0, 20.0, 30.0, 40.0, 50.0):
            tracker.record("parse", v)
        for v in (100.0, 200.0, 300.0, 400.0, 500.0):
            tracker.record("detect", v)

        snap = tracker.snapshot()
        assert set(snap.keys()) == {"parse", "detect"}
        # Detect percentiles must be ~10x parse percentiles.
        assert snap["detect"]["p50"] > snap["parse"]["p50"] * 5

    def test_buffer_eviction(self) -> None:
        tracker = StageLatencyTracker(maxlen=128)
        # Push 200 samples: only the last 128 survive.
        for i in range(200):
            tracker.record("storage", float(i))

        snap = tracker.snapshot()
        assert snap["storage"]["count"] == 128
        # The retained window is [72..199]; p50 should sit roughly mid-range.
        assert 130.0 <= snap["storage"]["p50"] <= 145.0

    def test_concurrent_record_and_snapshot(self) -> None:
        tracker = StageLatencyTracker()
        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            try:
                for i in range(2_000):
                    tracker.record("parse", float(i % 250))
            except BaseException as e:  # pragma: no cover - defensive
                errors.append(e)

        def reader() -> None:
            try:
                while not stop.is_set():
                    snap = tracker.snapshot()
                    if "parse" in snap:
                        bucket = snap["parse"]
                        # Sanity: every value is a real float and count is non-neg.
                        assert bucket["count"] >= 0
                        assert isinstance(bucket["p50"], float)
            except BaseException as e:  # pragma: no cover - defensive
                errors.append(e)

        writers = [threading.Thread(target=writer) for _ in range(4)]
        rdr = threading.Thread(target=reader)
        rdr.start()
        for t in writers:
            t.start()
        for t in writers:
            t.join()
        stop.set()
        rdr.join()

        assert errors == []
        # After all writers drain, at least one of the 8000 samples must be retained.
        final = tracker.snapshot()
        assert final["parse"]["count"] > 0

    def test_single_sample_yields_constant_percentiles(self) -> None:
        """``statistics.quantiles`` raises on n<2; tracker must handle it."""
        tracker = StageLatencyTracker()
        tracker.record("parse", 42.0)
        snap = tracker.snapshot()
        bucket = snap["parse"]
        assert bucket["count"] == 1
        assert bucket["p50"] == pytest.approx(42.0)
        assert bucket["p95"] == pytest.approx(42.0)
        assert bucket["p99"] == pytest.approx(42.0)

    def test_stage_cap(self, caplog: pytest.LogCaptureFixture) -> None:
        tracker = StageLatencyTracker(max_stages=4)
        with caplog.at_level(logging.WARNING, logger="seerflow.api.latency"):
            for i in range(8):
                tracker.record(f"stage_{i}", 1.0)

        snap = tracker.snapshot()
        # First 4 stages retained, last 4 silently dropped.
        assert len(snap) == 4
        assert set(snap.keys()) == {"stage_0", "stage_1", "stage_2", "stage_3"}
        # A single warning is emitted; further drops are silent.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
