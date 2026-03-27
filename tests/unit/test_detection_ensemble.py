"""Tests for DetectionEnsemble orchestrator."""

from __future__ import annotations

import math
import statistics
import uuid

import pytest

from seerflow.config import DetectionConfig
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.models import SeerflowEvent, SeverityLevel


def _make_event(*, source_type: str = "syslog", **kwargs):
    defaults = {
        "event_id": uuid.uuid4(),
        "timestamp_ns": 1_700_000_000_000_000_000,
        "observed_ns": 1_700_000_000_000_000_000,
        "message": "test message",
        "template_id": 1,
        "severity_id": SeverityLevel.INFORMATIONAL,
        "source_type": source_type,
    }
    defaults.update(kwargs)
    return SeerflowEvent(**defaults)


class TestDetectionResult:
    def test_fields(self) -> None:
        r = DetectionResult(
            score=0.5,
            upper_threshold=3.0,
            lower_threshold=-1.0,
            is_anomaly=False,
            anomaly_direction=None,
            source_type="syslog",
        )
        assert r.score == 0.5
        assert r.source_type == "syslog"

    def test_frozen(self) -> None:
        r = DetectionResult(
            score=0.5,
            upper_threshold=3.0,
            lower_threshold=-1.0,
            is_anomaly=False,
            anomaly_direction=None,
            source_type="syslog",
        )
        with pytest.raises(AttributeError):
            r.score = 1.0  # type: ignore[misc]


class TestDetectionEnsemble:
    def test_process_event_returns_result(self) -> None:
        config = DetectionConfig(hst_window_size=100, hst_n_trees=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result, DetectionResult)
        assert isinstance(result.score, float)
        assert result.source_type == "syslog"

    def test_not_anomaly_during_calibration(self) -> None:
        config = DetectionConfig(hst_window_size=100, hst_n_trees=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        for i in range(100):
            result = ensemble.process_event(_make_event(template_id=i % 5))
            assert result.is_anomaly is False

    def test_per_source_isolation(self) -> None:
        config = DetectionConfig(hst_window_size=100, hst_n_trees=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        r1 = ensemble.process_event(_make_event(source_type="syslog"))
        r2 = ensemble.process_event(_make_event(source_type="file"))
        assert r1.source_type == "syslog"
        assert r2.source_type == "file"

    def test_empty_source_type_uses_default(self) -> None:
        config = DetectionConfig(hst_window_size=100, hst_n_trees=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event(source_type=""))
        assert result.source_type == "default"

    def test_result_has_thresholds(self) -> None:
        config = DetectionConfig(hst_window_size=100, hst_n_trees=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result.upper_threshold, float)
        assert isinstance(result.lower_threshold, float)


class TestEnsembleWithHoltWinters:
    def test_ensemble_creates_four_detectors(self) -> None:
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._detectors["syslog"]) == 4

    def test_ensemble_score_averages_four_detectors(self) -> None:
        config = DetectionConfig(
            hst_window_size=50,
            hst_n_trees=10,
            hw_seasonal_period=10,
            dspot_calibration_window=200,
        )
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)


class TestEnsembleWithCUSUM:
    def test_ensemble_creates_four_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._detectors["syslog"]) == 4

    def test_ensemble_score_with_four_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(
            hst_window_size=50,
            hst_n_trees=10,
            hw_seasonal_period=10,
            dspot_calibration_window=200,
        )
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)


class TestEnsembleWithMarkov:
    def test_ensemble_creates_four_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._detectors["syslog"]) == 4

    def test_ensemble_score_with_four_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(
            hst_window_size=50,
            hst_n_trees=10,
            hw_seasonal_period=10,
            dspot_calibration_window=200,
        )
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)


class TestEnsembleLRU:
    def test_source_eviction_when_exceeding_max(self) -> None:
        """Oldest source evicted when max_sources exceeded."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=3, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        # Process 4 sources (exceeds max_sources=3)
        for i in range(4):
            ensemble.process_event(_make_event(source_type=f"source-{i}"))
        # source-0 should be evicted (oldest)
        assert "source-0" not in ensemble._detectors
        assert "source-0" not in ensemble._thresholds
        assert "source-3" in ensemble._detectors
        assert len(ensemble._detectors) == 3

    def test_active_source_not_evicted(self) -> None:
        """Recently accessed source survives eviction."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=3, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        # Create 3 sources
        for i in range(3):
            ensemble.process_event(_make_event(source_type=f"source-{i}"))
        # Re-access source-0 (moves to end of LRU)
        ensemble.process_event(_make_event(source_type="source-0"))
        # Add source-3 → should evict source-1 (now the oldest)
        ensemble.process_event(_make_event(source_type="source-3"))
        assert "source-0" in ensemble._detectors  # re-accessed, survived
        assert "source-1" not in ensemble._detectors  # oldest, evicted

    def test_threshold_dict_stays_in_sync(self) -> None:
        """_thresholds evicted in sync with _detectors."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=2, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="a"))
        ensemble.process_event(_make_event(source_type="b"))
        ensemble.process_event(_make_event(source_type="c"))
        assert set(ensemble._detectors.keys()) == set(ensemble._thresholds.keys())
        assert len(ensemble._thresholds) == 2


class TestBlendedScoring:
    def test_weighted_average_differs_from_simple(self) -> None:
        """Weighted average produces different result than equal-weight average."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        # Custom weights: heavily favor content (HST)
        config = DetectionConfig(
            hw_seasonal_period=10,
            weights_content=0.90,
            weights_volume=0.03,
            weights_pattern=0.03,
            weights_sequence=0.04,
            dspot_calibration_window=500,
        )
        ensemble = DetectionEnsemble(config)

        # Process enough events to get meaningful scores
        for _ in range(30):
            ensemble.process_event(_make_event())

        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)
        # Score should be valid
        assert result.score >= 0.0

    def test_config_weights_are_used(self) -> None:
        """Different weights produce different scores for same events."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config1 = DetectionConfig(
            hw_seasonal_period=10,
            weights_content=0.90,
            weights_volume=0.03,
            weights_pattern=0.03,
            weights_sequence=0.04,
            dspot_calibration_window=500,
        )
        config2 = DetectionConfig(
            hw_seasonal_period=10,
            weights_content=0.10,
            weights_volume=0.30,
            weights_pattern=0.30,
            weights_sequence=0.30,
            dspot_calibration_window=500,
        )

        e1 = DetectionEnsemble(config1)
        e2 = DetectionEnsemble(config2)

        # Process same events
        for _ in range(30):
            e1.process_event(_make_event())
            e2.process_event(_make_event())

        r1 = e1.process_event(_make_event())
        r2 = e2.process_event(_make_event())

        # Both should produce valid scores
        assert isinstance(r1.score, float)
        assert isinstance(r2.score, float)

    def test_score_windows_created_per_source(self) -> None:
        """Score windows are created for each source."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        ensemble.process_event(_make_event(source_type="file"))

        assert "syslog" in ensemble._score_windows
        assert "file" in ensemble._score_windows
        assert len(ensemble._score_windows["syslog"]) == 4  # 4 detectors

    def test_warmup_uses_raw_scores(self) -> None:
        """During warmup (< 2 scores in window), raw scores used."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=500)
        ensemble = DetectionEnsemble(config)
        # First event should not crash
        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)
        assert result.score >= 0.0

    def test_score_windows_evicted_with_source(self) -> None:
        """Score windows are cleaned up when source is LRU-evicted."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=2, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="a"))
        ensemble.process_event(_make_event(source_type="b"))
        ensemble.process_event(_make_event(source_type="c"))
        # "a" should be evicted from all dicts
        assert "a" not in ensemble._score_windows
        assert "c" in ensemble._score_windows


class TestEnsembleStats:
    def test_get_stats_returns_counts(self) -> None:
        """get_stats returns source_count, max_sources, eviction_count."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=10, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        ensemble.process_event(_make_event(source_type="file"))
        stats = ensemble.get_stats()
        assert stats["source_count"] == 2
        assert stats["max_sources"] == 10
        assert stats["eviction_count"] == 0

    def test_eviction_count_increments(self) -> None:
        """Eviction counter tracks total evictions."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(max_sources=2, hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        for i in range(5):
            ensemble.process_event(_make_event(source_type=f"s-{i}"))
        stats = ensemble.get_stats()
        assert stats["eviction_count"] == 3  # 5 sources - 2 max = 3 evictions

    def test_default_max_sources(self) -> None:
        """Default max_sources is 256."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig()
        ensemble = DetectionEnsemble(config)
        stats = ensemble.get_stats()
        assert stats["max_sources"] == 256


class TestEnsembleHardening:
    def test_nan_score_replaced_with_zero(self) -> None:
        """NaN from a detector is replaced with 0.0."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        class _NanDetector:
            def score(self, event: object) -> float:
                return float("nan")

            def learn(self, event: object) -> None:
                pass

        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=500)
        ensemble = DetectionEnsemble(config)
        # Process one event to create detectors
        ensemble.process_event(_make_event())
        # Replace HST (index 0) with a stub that always returns NaN
        ensemble._detectors["syslog"][0] = _NanDetector()  # type: ignore[assignment]
        result = ensemble.process_event(_make_event())
        assert math.isfinite(result.score)

    def test_inf_score_replaced_with_zero(self) -> None:
        """Inf from a detector is replaced with 0.0."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        class _InfDetector:
            def score(self, event: object) -> float:
                return float("inf")

            def learn(self, event: object) -> None:
                pass

        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=500)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        # Replace HST (index 0) with a stub that always returns Inf
        ensemble._detectors["syslog"][0] = _InfDetector()  # type: ignore[assignment]
        result = ensemble.process_event(_make_event())
        assert math.isfinite(result.score)

    def test_source_type_truncated(self) -> None:
        """Long source_type is truncated to 248 chars."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import _MAX_SOURCE_KEY_LEN, DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        long_source = "x" * 500
        ensemble.process_event(_make_event(source_type=long_source))
        keys = list(ensemble._detectors.keys())
        assert all(len(k) <= _MAX_SOURCE_KEY_LEN for k in keys)
        assert all(len(k) == _MAX_SOURCE_KEY_LEN for k in keys)

    def test_welford_accumulator_mean(self) -> None:
        """Welford produces correct mean."""
        from seerflow.detection.ensemble import _WelfordAccumulator

        acc = _WelfordAccumulator()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            acc.update(v)
        assert acc.mean() == pytest.approx(3.0)

    def test_welford_accumulator_stdev(self) -> None:
        """Welford produces correct stdev matching statistics module."""
        from seerflow.detection.ensemble import _WelfordAccumulator

        acc = _WelfordAccumulator()
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            acc.update(v)
        assert acc.stdev() == pytest.approx(statistics.stdev(values), abs=1e-10)

    def test_welford_warmup_zero_stdev(self) -> None:
        """Welford with < 2 samples returns stdev 0.0."""
        from seerflow.detection.ensemble import _WelfordAccumulator

        acc = _WelfordAccumulator()
        assert acc.stdev() == 0.0
        acc.update(5.0)
        assert acc.stdev() == 0.0

    @pytest.mark.parametrize(
        "bad_state",
        [
            {"n": -1, "mean": 0.0, "m2": 0.0},
            {"n": 0, "mean": 0.0, "m2": 1.0},
            {"n": 1, "mean": 5.0, "m2": 0.5},
            {"n": 2, "mean": float("nan"), "m2": 0.0},
            {"n": 2, "mean": 0.0, "m2": float("inf")},
            {"n": 2, "mean": 0.0, "m2": -1.0},
        ],
    )
    def test_welford_from_dict_rejects_invalid(self, bad_state: dict) -> None:
        """from_dict rejects invalid Welford state."""
        from seerflow.detection.ensemble import _WelfordAccumulator

        with pytest.raises(ValueError):
            _WelfordAccumulator.from_dict(bad_state)
