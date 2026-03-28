"""Tests for CUSUMDetector — change point detection."""

from __future__ import annotations

import uuid

import pytest

from seerflow.models import SeerflowEvent, SeverityLevel

_BUCKET_NS = 60 * 1_000_000_000


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
    from seerflow.detection.cusum import CUSUMDetector

    assert isinstance(detector, CUSUMDetector)
    for _ in range(count):
        detector.learn(_make_event(timestamp_ns=timestamp_ns))


class TestCUSUMDetector:
    def test_score_returns_float_in_range(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        score = detector.score(_make_event())
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_returns_zero_during_warmup(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=30)
        base_ns = 1_700_000_000_000_000_000
        # Process 11 buckets (less than warmup=30); bucket 10 triggers rollover for 0-9
        for i in range(11):
            ts = base_ns + i * _BUCKET_NS
            _send_events(detector, 5, ts)
        assert detector.score(_make_event()) == 0.0

    def test_upward_shift_detection(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=3.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline: 10 events per bucket for 16 buckets
        # Bucket 15 triggers rollover for bucket 14, completing the baseline
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 10, ts)

        baseline_score = detector.score(_make_event())

        # Sustained upward shift: 30 events per bucket for 10 buckets
        for bucket in range(16, 26):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 30, ts)

        shift_score = detector.score(_make_event())
        assert shift_score > baseline_score

    def test_downward_shift_detection(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=3.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline: 20 events per bucket for 16 buckets
        # Bucket 15 triggers rollover for bucket 14, completing the baseline
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 20, ts)

        baseline_score = detector.score(_make_event())

        # Sustained downward shift: 2 events per bucket for 10 buckets
        for bucket in range(16, 26):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 2, ts)

        shift_score = detector.score(_make_event())
        assert shift_score > baseline_score

    def test_reset_after_change_point(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=2.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline: 10 events per bucket for 16 buckets
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 10, ts)

        # Inject a massive one-bucket spike (1000 events) that is guaranteed to
        # exceed threshold=2.0 and trigger a hard reset in that single _update().
        spike_ts = base_ns + 16 * _BUCKET_NS
        _send_events(detector, 1000, spike_ts)

        # Flush the spike bucket by sending one event to bucket 17.
        # This triggers _update(1000) → score >= 1.0 → reset → _g_upper = _g_lower = 0.0.
        detector.learn(_make_event(timestamp_ns=spike_ts + _BUCKET_NS))

        # After the reset, _g values must be exactly 0.0 before bucket 17 accumulates.
        # Bucket 17 is now the current (open) bucket with count=1 — not yet flushed.
        assert detector._g_upper == 0.0
        assert detector._g_lower == 0.0

    def test_implements_detector_protocol(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector
        from seerflow.detection.protocols import Detector

        detector = CUSUMDetector()
        assert isinstance(detector, Detector)

    def test_serialize_deserialize_round_trip(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10)
        base_ns = 1_700_000_000_000_000_000
        for bucket in range(16):
            ts = base_ns + bucket * _BUCKET_NS
            _send_events(detector, 5, ts)

        data = detector.serialize()
        assert isinstance(data, bytes)

        restored = CUSUMDetector(warmup_buckets=10)
        restored.deserialize(data)

        test_event = _make_event(timestamp_ns=base_ns + 20 * _BUCKET_NS)
        assert detector.score(test_event) == pytest.approx(restored.score(test_event), abs=1e-10)

    def test_config_parameters_affect_state(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        d1 = CUSUMDetector(drift=0.1, threshold=10.0)
        d2 = CUSUMDetector(drift=0.9, threshold=2.0)
        assert d1._drift != d2._drift
        assert d1._threshold != d2._threshold

    def test_backward_timestamp_ignored(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        base_ns = 1_700_000_000_000_000_000
        detector.learn(_make_event(timestamp_ns=base_ns + _BUCKET_NS))
        count_before = detector._current_count
        # Send event with earlier timestamp
        detector.learn(_make_event(timestamp_ns=base_ns))
        assert detector._current_count == count_before

    def test_invalid_drift_raises(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        with pytest.raises(ValueError, match="drift must be positive"):
            CUSUMDetector(drift=0.0)

    def test_invalid_threshold_raises(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        with pytest.raises(ValueError, match="threshold must be positive"):
            CUSUMDetector(threshold=-1.0)

    def test_invalid_ema_alpha_raises(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        with pytest.raises(ValueError, match="ema_alpha must be in"):
            CUSUMDetector(ema_alpha=1.5)

    def test_invalid_warmup_raises(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        with pytest.raises(ValueError, match="warmup_buckets must be >= 1"):
            CUSUMDetector(warmup_buckets=0)

    def test_gap_bucket_handling(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=5)
        base_ns = 1_700_000_000_000_000_000
        detector.learn(_make_event(timestamp_ns=base_ns))
        detector.learn(_make_event(timestamp_ns=base_ns + _BUCKET_NS))
        t_before = detector._t
        # Skip 3 minutes
        detector.learn(_make_event(timestamp_ns=base_ns + 5 * _BUCKET_NS))
        assert detector._t >= t_before + 4

    def test_deserialize_rejects_invalid_drift(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        detector._drift = 0.0
        data = detector.serialize()
        fresh = CUSUMDetector()
        with pytest.raises(ValueError, match="drift"):
            fresh.deserialize(data)

    def test_deserialize_rejects_invalid_threshold(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        detector._threshold = -1.0
        data = detector.serialize()
        fresh = CUSUMDetector()
        with pytest.raises(ValueError, match="threshold"):
            fresh.deserialize(data)

    def test_deserialize_rejects_invalid_ema_alpha(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        detector._ema_alpha = 1.5
        data = detector.serialize()
        fresh = CUSUMDetector()
        with pytest.raises(ValueError, match="ema_alpha"):
            fresh.deserialize(data)

    def test_deserialize_rejects_negative_running_var(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        detector._running_var = -0.5
        data = detector.serialize()
        fresh = CUSUMDetector()
        with pytest.raises(ValueError, match="running_var"):
            fresh.deserialize(data)

    def test_deserialize_rejects_nan_g_upper(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector()
        detector._g_upper = float("nan")
        data = detector.serialize()
        fresh = CUSUMDetector()
        with pytest.raises(ValueError, match="g_upper"):
            fresh.deserialize(data)
