"""Tests for HoltWintersDetector — volume anomaly detection."""

from __future__ import annotations

import uuid

import pytest

from seerflow.models import SeerflowEvent, SeverityLevel

_BUCKET_NS = 60 * 1_000_000_000  # 1 minute in nanoseconds


def _make_event(
    *,
    timestamp_ns: int = 1_700_000_000_000_000_000,
    source_type: str = "syslog",
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns,
        message="test",
        source_type=source_type,
        severity_id=SeverityLevel.INFORMATIONAL,
    )


def _send_events(detector: object, count: int, timestamp_ns: int) -> None:
    """Send count events at the given timestamp (same bucket)."""
    from seerflow.detection.holtwinters import HoltWintersDetector

    assert isinstance(detector, HoltWintersDetector)
    for _ in range(count):
        detector.learn(_make_event(timestamp_ns=timestamp_ns))


class TestHoltWintersDetector:
    def test_score_returns_float_in_range(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector()
        event = _make_event()
        score = detector.score(event)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_returns_zero_during_warmup(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector(seasonal_period=10)
        base_ns = 1_700_000_000_000_000_000
        # Process 5 buckets (less than seasonal_period=10)
        for i in range(5):
            event = _make_event(timestamp_ns=base_ns + i * _BUCKET_NS)
            detector.learn(event)
        score = detector.score(_make_event(timestamp_ns=base_ns + 5 * _BUCKET_NS))
        assert score == 0.0

    def test_learn_increments_bucket_counter(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector()
        event = _make_event()
        detector.learn(event)
        assert detector._current_count == 1
        detector.learn(event)
        assert detector._current_count == 2

    def test_bucket_rollover_triggers_update(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector()
        base_ns = 1_700_000_000_000_000_000
        # Events in bucket 0
        detector.learn(_make_event(timestamp_ns=base_ns))
        detector.learn(_make_event(timestamp_ns=base_ns))
        assert detector._t == 0  # no update yet
        # Event in bucket 1 triggers update for bucket 0
        detector.learn(_make_event(timestamp_ns=base_ns + _BUCKET_NS))
        assert detector._t >= 1  # at least one update fired

    def test_spike_detection(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector(seasonal_period=10)
        base_ns = 1_700_000_000_000_000_000
        # Train with steady 5 events per bucket for 16 buckets (past warmup)
        # Each bucket's rollover is triggered naturally by the next bucket's events
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 5, ts)

        normal_score = detector.score(_make_event())

        # Now inject a spike: 50 events in one bucket
        spike_ts = base_ns + 16 * _BUCKET_NS
        for _ in range(50):
            detector.learn(_make_event(timestamp_ns=spike_ts))
        # Trigger rollover
        detector.learn(_make_event(timestamp_ns=spike_ts + _BUCKET_NS))

        spike_score = detector.score(_make_event(timestamp_ns=spike_ts + _BUCKET_NS))
        assert spike_score > normal_score

    def test_implements_detector_protocol(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector
        from seerflow.detection.protocols import Detector

        detector = HoltWintersDetector()
        assert isinstance(detector, Detector)

    def test_serialize_deserialize_round_trip(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector(seasonal_period=10)
        base_ns = 1_700_000_000_000_000_000
        # Train with some data
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 5, ts)

        data = detector.serialize()
        assert isinstance(data, bytes)
        assert len(data) > 0

        restored = HoltWintersDetector(seasonal_period=10)
        restored.deserialize(data)

        # Both should produce the same score
        test_event = _make_event(timestamp_ns=base_ns + 20 * _BUCKET_NS)
        assert detector.score(test_event) == pytest.approx(restored.score(test_event), abs=1e-10)

    def test_drop_detection(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector(seasonal_period=10)
        base_ns = 1_700_000_000_000_000_000
        # Train with steady 20 events per bucket for 16 buckets (past warmup)
        # Rollover is triggered naturally when events arrive in the next bucket
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 20, ts)

        normal_score = detector.score(_make_event())

        # Now inject silence: 0 events in one bucket (just trigger rollover)
        silence_ts = base_ns + 16 * _BUCKET_NS
        detector.learn(_make_event(timestamp_ns=silence_ts))
        # Trigger rollover with only 1 event (near-silence)
        detector.learn(_make_event(timestamp_ns=silence_ts + _BUCKET_NS))

        drop_score = detector.score(_make_event(timestamp_ns=silence_ts + _BUCKET_NS))
        assert drop_score > normal_score

    def test_gap_bucket_handling(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        detector = HoltWintersDetector(seasonal_period=10)
        base_ns = 1_700_000_000_000_000_000
        # Process a few buckets
        detector.learn(_make_event(timestamp_ns=base_ns))
        detector.learn(_make_event(timestamp_ns=base_ns + _BUCKET_NS))
        t_before = detector._t
        # Skip 3 minutes (gap of 3 buckets)
        detector.learn(_make_event(timestamp_ns=base_ns + 5 * _BUCKET_NS))
        # Should have advanced by: 1 (bucket 1) + 3 (gap buckets)
        assert detector._t >= t_before + 4

    def test_config_parameters_affect_behavior(self) -> None:
        from seerflow.detection.holtwinters import HoltWintersDetector

        d1 = HoltWintersDetector(seasonal_period=10, alpha=0.9)
        d2 = HoltWintersDetector(seasonal_period=10, alpha=0.1)
        assert d1._alpha != d2._alpha
