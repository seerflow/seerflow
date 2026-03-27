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
        # Process 10 buckets (less than warmup=30)
        for i in range(10):
            ts = base_ns + i * _BUCKET_NS
            for _ in range(5):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1
        assert detector.score(_make_event()) == 0.0

    def test_upward_shift_detection(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=3.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline: 10 events per bucket for 15 buckets
        for bucket in range(15):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(10):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        baseline_score = detector.score(_make_event())

        # Sustained upward shift: 30 events per bucket for 10 buckets
        for bucket in range(15, 25):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(30):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        shift_score = detector.score(_make_event())
        assert shift_score > baseline_score

    def test_downward_shift_detection(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=3.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline: 20 events per bucket for 15 buckets
        for bucket in range(15):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(20):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        baseline_score = detector.score(_make_event())

        # Sustained downward shift: 2 events per bucket for 10 buckets
        for bucket in range(15, 25):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(2):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        shift_score = detector.score(_make_event())
        assert shift_score > baseline_score

    def test_reset_after_change_point(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10, drift=0.5, threshold=2.0)
        base_ns = 1_700_000_000_000_000_000
        # Establish baseline
        for bucket in range(15):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(10):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        # Force a large shift to trigger reset
        for bucket in range(15, 30):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(100):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

        # After sustained shift, g should have reset at some point
        # Score should be lower than 1.0 after reset + adaptation
        assert detector._g_upper < detector._threshold or detector._g_lower < detector._threshold

    def test_implements_detector_protocol(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector
        from seerflow.detection.protocols import Detector

        detector = CUSUMDetector()
        assert isinstance(detector, Detector)

    def test_serialize_deserialize_round_trip(self) -> None:
        from seerflow.detection.cusum import CUSUMDetector

        detector = CUSUMDetector(warmup_buckets=10)
        base_ns = 1_700_000_000_000_000_000
        for bucket in range(15):
            ts = base_ns + bucket * _BUCKET_NS
            for _ in range(5):
                detector.learn(_make_event(timestamp_ns=ts))
            detector.learn(_make_event(timestamp_ns=ts + _BUCKET_NS))
            detector._current_count -= 1

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
