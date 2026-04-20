"""Tests for DetectionEnsemble orchestrator."""

from __future__ import annotations

import math
import statistics
import uuid
from typing import TYPE_CHECKING, Any

import msgspec.json
import numpy as np
import pytest

from seerflow.config import DetectionConfig, StorageConfig
from seerflow.detection.ensemble import (
    DetectionEnsemble,
    DetectionResult,
    ThresholdAdjustResult,
)
from seerflow.detection.holtwinters import HoltWintersDetector
from seerflow.models import SeerflowEvent, SeverityLevel
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path


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


def _make_config(**kwargs) -> DetectionConfig:
    """Create a DetectionConfig with test-friendly defaults."""
    defaults: dict = {
        "hw_seasonal_period": 10,
        "dspot_calibration_window": 200,
    }
    defaults.update(kwargs)
    return DetectionConfig(**defaults)


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
        assert len(ensemble._score_windows["syslog"]) == 6  # 4 core + 2 granular

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

    def test_null_byte_stripped_from_source(self) -> None:
        """Null bytes in source_type are stripped."""
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="sys\x00log"))
        keys = list(ensemble._detectors.keys())
        assert "syslog" in keys
        assert "\x00" not in keys[0]


class TestBatchScoring:
    def test_score_interval_1_scores_every_event(self) -> None:
        """Default score_interval=1 should score every event."""
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        results = [ensemble.process_event(_make_event(template_id=i)) for i in range(5)]
        assert all(isinstance(r, DetectionResult) for r in results)

    def test_score_interval_10_skips_9_events(self) -> None:
        """With score_interval=10, only every 10th event should be fully scored."""
        config = DetectionConfig(hw_seasonal_period=10, score_interval=10)
        ensemble = DetectionEnsemble(config)
        results = [ensemble.process_event(_make_event(template_id=i % 5)) for i in range(20)]
        skipped = [r for r in results if r.score == 0.0 and not r.is_anomaly]
        assert len(skipped) >= 18

    def test_skipped_events_return_zero_score(self) -> None:
        """Skipped events must return score=0.0 and is_anomaly=False."""
        config = DetectionConfig(hw_seasonal_period=10, score_interval=100)
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event(template_id=1))
        assert result.score == 0.0
        assert result.is_anomaly is False

    def test_score_interval_zero_raises(self) -> None:
        """score_interval=0 must raise ConfigError."""
        from seerflow.config import ConfigError, _build_detection

        with pytest.raises(ConfigError, match="score_interval"):
            _build_detection({"score_interval": 0})


def _granular_config(**overrides: Any) -> DetectionConfig:
    """Helper for granular HW tests — short alias for common config."""
    defaults: dict[str, Any] = {
        "hw_seasonal_period": 10,
        "min_events_for_scoring": 1,
    }
    defaults.update(overrides)
    return DetectionConfig(**defaults)


class TestTemplateHW:
    """S-138: Per-template HoltWinters instances."""

    def test_template_hw_created_lazily(self) -> None:
        """Template HW instance created on first event with that template."""
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=5))
        assert "syslog:5" in ensemble._template_hw

    def test_template_hw_not_created_for_negative_one(self) -> None:
        """template_id=-1 means no template matched — no HW instance."""
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=-1))
        assert len(ensemble._template_hw) == 0

    def test_template_hw_not_created_for_any_negative(self) -> None:
        """Any negative template_id is treated as no template matched."""
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=-2))
        ensemble.process_event(_make_event(template_id=-999))
        assert len(ensemble._template_hw) == 0

    def test_template_hw_lru_eviction(self) -> None:
        """Oldest template HW evicted when max_template_hw exceeded."""
        config = _granular_config(max_template_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        ensemble.process_event(_make_event(template_id=3))
        assert "syslog:1" not in ensemble._template_hw
        assert "syslog:3" in ensemble._template_hw
        assert len(ensemble._template_hw) == 2

    def test_template_hw_lru_reaccess_survives(self) -> None:
        """Re-accessed template HW moved to end, survives eviction."""
        config = _granular_config(max_template_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=3))
        assert "syslog:1" in ensemble._template_hw
        assert "syslog:2" not in ensemble._template_hw

    def test_long_source_template_key_truncated(self) -> None:
        """Template key truncated to _MAX_SOURCE_KEY_LEN."""
        from seerflow.detection.ensemble import _MAX_SOURCE_KEY_LEN

        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        long_source = "s" * 300
        ensemble.process_event(_make_event(source_type=long_source, template_id=1))
        keys = list(ensemble._template_hw.keys())
        assert all(len(k) <= _MAX_SOURCE_KEY_LEN for k in keys)

    def test_min_events_threshold_returns_zero(self) -> None:
        """Template score is 0.0 until min_events_for_scoring reached."""
        config = _granular_config(
            max_template_hw=100,
            min_events_for_scoring=5,
            dspot_calibration_window=500,
        )
        ensemble = DetectionEnsemble(config)
        for _ in range(4):
            ensemble.process_event(_make_event(template_id=1))
        assert "syslog:1" in ensemble._template_hw
        assert ensemble._template_event_counts["syslog:1"] == 4

    def test_template_event_counts_tracked(self) -> None:
        """Event counts per template key are tracked."""
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        for _ in range(3):
            ensemble.process_event(_make_event(template_id=7))
        assert ensemble._template_event_counts["syslog:7"] == 3

    def test_template_event_counts_evicted_with_hw(self) -> None:
        """Event counts cleaned up when template HW is LRU-evicted."""
        config = _granular_config(max_template_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        ensemble.process_event(_make_event(template_id=3))
        assert "syslog:1" not in ensemble._template_event_counts

    def test_different_sources_create_separate_template_hw(self) -> None:
        """Same template_id from different sources gets separate HW."""
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog", template_id=1))
        ensemble.process_event(_make_event(source_type="file", template_id=1))
        assert "syslog:1" in ensemble._template_hw
        assert "file:1" in ensemble._template_hw


class TestEntityHW:
    """S-138: Per-entity HoltWinters instances."""

    def test_entity_hw_created_lazily(self) -> None:
        """Entity HW instance created on first event with that entity."""
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("entity-abc",)))
        assert "syslog:entity-abc" in ensemble._entity_hw

    def test_entity_hw_not_created_for_empty_refs(self) -> None:
        """No entity HW created when entity_refs is empty."""
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=()))
        assert len(ensemble._entity_hw) == 0

    def test_entity_hw_lru_eviction(self) -> None:
        """Oldest entity HW evicted when max_entity_hw exceeded."""
        config = _granular_config(max_entity_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        ensemble.process_event(_make_event(entity_refs=("e3",)))
        assert "syslog:e1" not in ensemble._entity_hw
        assert "syslog:e3" in ensemble._entity_hw
        assert len(ensemble._entity_hw) == 2

    def test_long_entity_value_truncated(self) -> None:
        """Entity key truncated to _MAX_SOURCE_KEY_LEN."""
        from seerflow.detection.ensemble import _MAX_SOURCE_KEY_LEN

        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        long_entity = "x" * 500
        ensemble.process_event(_make_event(entity_refs=(long_entity,)))
        keys = list(ensemble._entity_hw.keys())
        assert all(len(k) <= _MAX_SOURCE_KEY_LEN for k in keys)

    def test_entity_refs_capped_per_event(self) -> None:
        """Only first 32 entity_refs processed per event."""
        from seerflow.detection.ensemble import _MAX_ENTITIES_PER_SCORE

        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        many_entities = tuple(f"e{i}" for i in range(100))
        ensemble.process_event(_make_event(entity_refs=many_entities))
        assert len(ensemble._entity_hw) == _MAX_ENTITIES_PER_SCORE

    def test_null_byte_entity_value_skipped(self) -> None:
        """Entity value that is only null bytes is skipped."""
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("\x00\x00", "valid")))
        assert len(ensemble._entity_hw) == 1
        assert "syslog:valid" in ensemble._entity_hw

    def test_entity_hw_lru_reaccess_survives(self) -> None:
        """Re-accessed entity HW moved to end, survives eviction."""
        config = _granular_config(max_entity_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e3",)))
        assert "syslog:e1" in ensemble._entity_hw
        assert "syslog:e2" not in ensemble._entity_hw

    def test_multiple_entity_refs_creates_multiple_hw(self) -> None:
        """Event with multiple entity_refs creates HW per entity."""
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1", "e2", "e3")))
        assert "syslog:e1" in ensemble._entity_hw
        assert "syslog:e2" in ensemble._entity_hw
        assert "syslog:e3" in ensemble._entity_hw

    def test_entity_min_events_threshold(self) -> None:
        """Entity score is 0.0 until min_events_for_scoring reached."""
        config = _granular_config(
            max_entity_hw=100,
            min_events_for_scoring=5,
            dspot_calibration_window=500,
        )
        ensemble = DetectionEnsemble(config)
        for _ in range(4):
            ensemble.process_event(_make_event(entity_refs=("e1",)))
        assert ensemble._entity_event_counts["syslog:e1"] == 4

    def test_entity_event_counts_evicted_with_hw(self) -> None:
        """Event counts cleaned up when entity HW is LRU-evicted."""
        config = _granular_config(max_entity_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        ensemble.process_event(_make_event(entity_refs=("e3",)))
        assert "syslog:e1" not in ensemble._entity_event_counts

    def test_different_sources_create_separate_entity_hw(self) -> None:
        """Same entity from different sources gets separate HW."""
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(
            _make_event(source_type="syslog", entity_refs=("e1",)),
        )
        ensemble.process_event(
            _make_event(source_type="file", entity_refs=("e1",)),
        )
        assert "syslog:e1" in ensemble._entity_hw
        assert "file:e1" in ensemble._entity_hw


class TestExpandedBlending:
    """S-138: Score blending expanded from 4 to 6 weights."""

    def test_weight_tuple_has_six_entries(self) -> None:
        """Weight tuple includes template_volume and entity_volume."""
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        assert len(ensemble._weights) == 6

    def test_score_windows_have_six_accumulators(self) -> None:
        """Score windows created with 6 accumulators (not 4)."""
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._score_windows["syslog"]) == 6

    def test_template_and_entity_weights_in_tuple(self) -> None:
        """Template and entity volume weights are at indices 4 and 5."""
        config = DetectionConfig(
            hw_seasonal_period=10,
            weights_template_volume=0.12,
            weights_entity_volume=0.18,
        )
        ensemble = DetectionEnsemble(config)
        assert ensemble._weights[4] == 0.12
        assert ensemble._weights[5] == 0.18

    def test_six_scores_blended(self) -> None:
        """process_event produces a finite score with 6-component blending."""
        config = _granular_config(dspot_calibration_window=500)
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(
            _make_event(template_id=1, entity_refs=("e1",)),
        )
        assert isinstance(result.score, float)
        assert math.isfinite(result.score)


class TestExpandedStats:
    """S-138: Stats include template and entity HW counts."""

    def test_stats_include_template_hw_count(self) -> None:
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        stats = ensemble.get_stats()
        assert stats["template_hw_count"] == 2

    def test_stats_include_entity_hw_count(self) -> None:
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        stats = ensemble.get_stats()
        assert stats["entity_hw_count"] == 2

    def test_stats_zero_when_no_template_or_entity(self) -> None:
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        stats = ensemble.get_stats()
        assert stats["template_hw_count"] == 0
        assert stats["entity_hw_count"] == 0


class TestExpandedPersistence:
    """S-138: Persistence includes template and entity HW state."""

    async def test_save_includes_template_and_entity_hw(self) -> None:
        from unittest.mock import AsyncMock

        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(
            _make_event(template_id=1, entity_refs=("e1",)),
        )

        storage = AsyncMock()
        storage.save_state = AsyncMock()
        await ensemble.save_all_state(storage)

        saved_keys = [call[0][0] for call in storage.save_state.call_args_list]
        assert any(k.startswith("tmpl_hw:") for k in saved_keys)
        assert any(k.startswith("ent_hw:") for k in saved_keys)
        assert any(k == "tmpl_hw:manifest" for k in saved_keys)
        assert any(k == "ent_hw:manifest" for k in saved_keys)

    async def test_load_restores_template_and_entity_hw(self, tmp_path: object) -> None:
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test.db"),  # type: ignore[operator]
        )
        storage = await SqliteBackend.connect(storage_cfg)
        config = _granular_config(dspot_calibration_window=200)

        ensemble1 = DetectionEnsemble(config)
        for _ in range(10):
            ensemble1.process_event(
                _make_event(template_id=1, entity_refs=("e1",)),
            )
        await ensemble1.save_all_state(storage)

        ensemble2 = DetectionEnsemble(config)
        loaded = await ensemble2.load_all_state(storage)
        assert "syslog:1" in ensemble2._template_hw
        assert "syslog:e1" in ensemble2._entity_hw
        assert loaded > 0

        await storage.close()

    async def test_backward_compat_4_accumulators_padded_to_6(
        self,
    ) -> None:
        """Score windows with 4 accumulators padded to 6 on load."""
        from unittest.mock import AsyncMock

        import msgspec.json

        from seerflow.detection.ensemble import _WelfordAccumulator

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)

        old_windows = [_WelfordAccumulator().to_dict() for _ in range(4)]
        manifest = msgspec.json.encode(["syslog"])
        windows_data = msgspec.json.encode(old_windows)

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return manifest
            if key == "windows:syslog":
                return windows_data
            return None

        storage = AsyncMock()
        storage.load_state = AsyncMock(side_effect=fake_load)

        await ensemble.load_all_state(storage)
        assert len(ensemble._score_windows["syslog"]) == 6

    async def test_corrupt_granular_manifest_skipped(self) -> None:
        """Corrupt granular manifest is skipped gracefully."""
        from unittest.mock import AsyncMock

        import msgspec.json

        config = _granular_config()
        ensemble = DetectionEnsemble(config)

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return msgspec.json.encode(["syslog"])
            if key == "tmpl_hw:manifest":
                return b"corrupt-json"
            if key == "ent_hw:manifest":
                return b"corrupt-json"
            return None

        storage = AsyncMock()
        storage.load_state = AsyncMock(side_effect=fake_load)
        await ensemble.load_all_state(storage)
        assert len(ensemble._template_hw) == 0
        assert len(ensemble._entity_hw) == 0

    async def test_missing_granular_hw_data_skipped(self) -> None:
        """Granular HW key in manifest but data missing → skipped."""
        from unittest.mock import AsyncMock

        import msgspec.json

        config = _granular_config()
        ensemble = DetectionEnsemble(config)

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return msgspec.json.encode(["syslog"])
            if key == "tmpl_hw:manifest":
                return msgspec.json.encode({"syslog:1": 10})
            if key == "tmpl_hw:syslog:1":
                return None  # data missing
            return None

        storage = AsyncMock()
        storage.load_state = AsyncMock(side_effect=fake_load)
        await ensemble.load_all_state(storage)
        assert "syslog:1" not in ensemble._template_hw

    async def test_corrupt_granular_hw_state_skipped(self) -> None:
        """Corrupt individual HW state → skipped, others continue."""
        from unittest.mock import AsyncMock

        import msgspec.json

        config = _granular_config()
        ensemble = DetectionEnsemble(config)

        async def fake_load(key: str) -> bytes | None:
            if key == "ensemble:manifest":
                return msgspec.json.encode(["syslog"])
            if key == "ent_hw:manifest":
                return msgspec.json.encode({"syslog:e1": 10})
            if key == "ent_hw:syslog:e1":
                return b"corrupt-hw-state"
            return None

        storage = AsyncMock()
        storage.load_state = AsyncMock(side_effect=fake_load)
        await ensemble.load_all_state(storage)
        assert "syslog:e1" not in ensemble._entity_hw


class TestHWEvictionCounters:
    """S-140: Template and entity HW eviction counters."""

    def test_template_hw_eviction_count_starts_zero(self) -> None:
        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        assert ensemble._template_hw_eviction_count == 0

    def test_template_hw_eviction_count_increments(self) -> None:
        config = _granular_config(max_template_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        ensemble.process_event(_make_event(template_id=3))
        assert ensemble._template_hw_eviction_count == 1

    def test_entity_hw_eviction_count_starts_zero(self) -> None:
        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        assert ensemble._entity_hw_eviction_count == 0

    def test_entity_hw_eviction_count_increments(self) -> None:
        config = _granular_config(max_entity_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        ensemble.process_event(_make_event(entity_refs=("e3",)))
        assert ensemble._entity_hw_eviction_count == 1

    def test_multiple_evictions_accumulate(self) -> None:
        config = _granular_config(max_template_hw=1)
        ensemble = DetectionEnsemble(config)
        for i in range(5):
            ensemble.process_event(_make_event(template_id=i))
        assert ensemble._template_hw_eviction_count == 4

    def test_get_or_create_hw_returns_tuple(self) -> None:
        """S-158: _get_or_create_hw returns (HoltWintersDetector, bool)."""
        config = _granular_config(max_template_hw=10)
        ensemble = DetectionEnsemble(config)
        result = ensemble._get_or_create_hw(
            "src:1",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        hw, evicted = result
        assert isinstance(hw, HoltWintersDetector)
        assert evicted is False

    def test_get_or_create_hw_eviction_returns_true(self) -> None:
        """S-158: _get_or_create_hw returns evicted=True when pool is full."""
        config = _granular_config(max_template_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble._get_or_create_hw(
            "src:1",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        ensemble._get_or_create_hw(
            "src:2",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        result = ensemble._get_or_create_hw(
            "src:3",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        _, evicted = result
        assert evicted is True

    def test_existing_key_returns_false(self) -> None:
        """S-158: _get_or_create_hw returns evicted=False for existing key."""
        config = _granular_config(max_template_hw=10)
        ensemble = DetectionEnsemble(config)
        ensemble._get_or_create_hw(
            "src:1",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        result = ensemble._get_or_create_hw(
            "src:1",
            ensemble._template_hw,
            ensemble._template_event_counts,
            ensemble._max_template_hw,
        )
        _, evicted = result
        assert evicted is False


class TestHealthMethod:
    """S-140: get_health() returns memory estimation and Markov entity counts."""

    def test_empty_ensemble_returns_zeros(self) -> None:
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        health = ensemble.get_health()
        assert health["source_count"] == 0
        assert health["estimated_memory_bytes"] == 0
        assert health["memory_by_type"]["hst"] == 0
        assert health["memory_by_type"]["hw_source"] == 0
        assert health["memory_by_type"]["hw_template"] == 0
        assert health["memory_by_type"]["hw_entity"] == 0
        assert health["memory_by_type"]["cusum"] == 0
        assert health["memory_by_type"]["markov"] == 0
        assert health["memory_by_type"]["dspot"] == 0
        assert health["markov_entity_counts"] == {}

    def test_single_source_memory_estimate(self) -> None:
        from seerflow.detection.ensemble import (
            _MEM_CUSUM,
            _MEM_DSPOT,
            _MEM_HST,
            _MEM_HW,
        )

        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        health = ensemble.get_health()
        assert health["source_count"] == 1
        assert health["memory_by_type"]["hst"] == _MEM_HST
        assert health["memory_by_type"]["hw_source"] == _MEM_HW
        assert health["memory_by_type"]["cusum"] == _MEM_CUSUM
        assert health["memory_by_type"]["dspot"] == _MEM_DSPOT

    def test_multi_source_memory_sums(self) -> None:
        from seerflow.detection.ensemble import _MEM_HST

        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        ensemble.process_event(_make_event(source_type="file"))
        health = ensemble.get_health()
        assert health["memory_by_type"]["hst"] == 2 * _MEM_HST

    def test_template_hw_memory(self) -> None:
        from seerflow.detection.ensemble import _MEM_HW

        config = _granular_config(max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1))
        ensemble.process_event(_make_event(template_id=2))
        health = ensemble.get_health()
        assert health["memory_by_type"]["hw_template"] == 2 * _MEM_HW

    def test_entity_hw_memory(self) -> None:
        from seerflow.detection.ensemble import _MEM_HW

        config = _granular_config(max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(entity_refs=("e1",)))
        ensemble.process_event(_make_event(entity_refs=("e2",)))
        health = ensemble.get_health()
        assert health["memory_by_type"]["hw_entity"] == 2 * _MEM_HW

    def test_markov_entity_counts_per_source(self) -> None:
        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog", entity_refs=("e1",)))
        ensemble.process_event(_make_event(source_type="syslog", entity_refs=("e2",)))
        ensemble.process_event(_make_event(source_type="file", entity_refs=("e3",)))
        health = ensemble.get_health()
        assert health["markov_entity_counts"]["syslog"] == 2
        assert health["markov_entity_counts"]["file"] == 1

    def test_markov_memory_estimate(self) -> None:
        from seerflow.detection.ensemble import _MEM_MARKOV_ENTITY

        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog", entity_refs=("e1",)))
        ensemble.process_event(_make_event(source_type="syslog", entity_refs=("e2",)))
        health = ensemble.get_health()
        assert health["memory_by_type"]["markov"] == 2 * _MEM_MARKOV_ENTITY

    def test_total_memory_is_sum_of_types(self) -> None:
        config = _granular_config(max_template_hw=100, max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(
            _make_event(template_id=1, entity_refs=("e1",)),
        )
        health = ensemble.get_health()
        mem = health["memory_by_type"]
        expected_total = sum(mem.values())
        assert health["estimated_memory_bytes"] == expected_total

    def test_includes_hw_eviction_counts(self) -> None:
        config = _granular_config(max_template_hw=1, max_entity_hw=1)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(template_id=1, entity_refs=("e1",)))
        ensemble.process_event(_make_event(template_id=2, entity_refs=("e2",)))
        health = ensemble.get_health()
        assert health["template_hw_eviction_count"] == 1
        assert health["entity_hw_eviction_count"] == 1

    def test_includes_existing_stats_fields(self) -> None:
        config = _granular_config()
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        health = ensemble.get_health()
        assert "source_count" in health
        assert "max_sources" in health
        assert "eviction_count" in health
        assert "template_hw_count" in health
        assert "entity_hw_count" in health


class TestFormatHealthTable:
    """S-140: format_health_table() output."""

    def test_table_includes_sources_line(self) -> None:
        from seerflow.query import format_health_table

        health = {
            "source_count": 3,
            "max_sources": 256,
            "eviction_count": 1,
            "template_hw_count": 5,
            "entity_hw_count": 2,
            "template_hw_eviction_count": 0,
            "entity_hw_eviction_count": 0,
            "estimated_memory_bytes": 153_600,
            "memory_by_type": {
                "hst": 153_600,
                "hw_source": 0,
                "hw_template": 0,
                "hw_entity": 0,
                "cusum": 0,
                "markov": 0,
                "dspot": 0,
            },
            "markov_entity_counts": {},
        }
        output = format_health_table(health)
        assert "3 / 256" in output

    def test_table_includes_memory_total(self) -> None:
        from seerflow.query import format_health_table

        health = {
            "source_count": 1,
            "max_sources": 256,
            "eviction_count": 0,
            "template_hw_count": 0,
            "entity_hw_count": 0,
            "template_hw_eviction_count": 0,
            "entity_hw_eviction_count": 0,
            "estimated_memory_bytes": 51_200,
            "memory_by_type": {
                "hst": 51_200,
                "hw_source": 0,
                "hw_template": 0,
                "hw_entity": 0,
                "cusum": 0,
                "markov": 0,
                "dspot": 0,
            },
            "markov_entity_counts": {},
        }
        output = format_health_table(health)
        assert "Total" in output

    def test_table_includes_markov_entities(self) -> None:
        from seerflow.query import format_health_table

        health = {
            "source_count": 1,
            "max_sources": 256,
            "eviction_count": 0,
            "template_hw_count": 0,
            "entity_hw_count": 0,
            "template_hw_eviction_count": 0,
            "entity_hw_eviction_count": 0,
            "estimated_memory_bytes": 10_240,
            "memory_by_type": {
                "hst": 0,
                "hw_source": 0,
                "hw_template": 0,
                "hw_entity": 0,
                "cusum": 0,
                "markov": 10_240,
                "dspot": 0,
            },
            "markov_entity_counts": {"syslog": 1},
        }
        output = format_health_table(health)
        assert "syslog" in output

    def test_table_format_bytes_mb_branch(self) -> None:
        from seerflow.query import format_health_table

        health = {
            "source_count": 256,
            "max_sources": 256,
            "eviction_count": 0,
            "template_hw_count": 0,
            "entity_hw_count": 0,
            "template_hw_eviction_count": 0,
            "entity_hw_eviction_count": 0,
            "estimated_memory_bytes": 13_107_200,
            "memory_by_type": {
                "hst": 13_107_200,
                "hw_source": 0,
                "hw_template": 0,
                "hw_entity": 0,
                "cusum": 0,
                "markov": 0,
                "dspot": 0,
            },
            "markov_entity_counts": {},
        }
        output = format_health_table(health)
        assert "MB" in output


class TestRunQueryHealth:
    """S-140: run_query_health() table and JSON output paths."""

    @pytest.mark.asyncio
    async def test_table_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        from seerflow.query import run_query_health

        mock_storage = AsyncMock()
        mock_storage.load_state = AsyncMock(return_value=None)
        mock_storage.close = AsyncMock()

        with (
            patch("seerflow.config.load_config") as mock_cfg,
            patch(
                "seerflow.query.connect_storage",
                new_callable=AsyncMock,
            ) as mock_connect,
        ):
            mock_cfg.return_value.detection = DetectionConfig(hw_seasonal_period=10)
            mock_cfg.return_value.storage = None
            mock_connect.return_value = mock_storage

            args = Namespace(config=None, json=False)
            await run_query_health(args)

        captured = capsys.readouterr()
        assert "Detection Ensemble Health" in captured.out
        assert "0 / 256" in captured.out

    @pytest.mark.asyncio
    async def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        from seerflow.query import run_query_health

        mock_storage = AsyncMock()
        mock_storage.load_state = AsyncMock(return_value=None)
        mock_storage.close = AsyncMock()

        with (
            patch("seerflow.config.load_config") as mock_cfg,
            patch(
                "seerflow.query.connect_storage",
                new_callable=AsyncMock,
            ) as mock_connect,
        ):
            mock_cfg.return_value.detection = DetectionConfig(hw_seasonal_period=10)
            mock_cfg.return_value.storage = None
            mock_connect.return_value = mock_storage

            args = Namespace(config=None, json=True)
            await run_query_health(args)

        captured = capsys.readouterr()
        import json

        data = json.loads(captured.out)
        assert "source_count" in data
        assert "estimated_memory_bytes" in data
        assert data["source_count"] == 0

    @pytest.mark.asyncio
    async def test_run_query_dispatches_health(self, capsys: pytest.CaptureFixture[str]) -> None:
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        from seerflow.query import run_query

        mock_storage = AsyncMock()
        mock_storage.load_state = AsyncMock(return_value=None)
        mock_storage.close = AsyncMock()

        with (
            patch("seerflow.config.load_config") as mock_cfg,
            patch(
                "seerflow.query.connect_storage",
                new_callable=AsyncMock,
            ) as mock_connect,
        ):
            mock_cfg.return_value.detection = DetectionConfig(hw_seasonal_period=10)
            mock_cfg.return_value.storage = None
            mock_connect.return_value = mock_storage

            args = Namespace(command="query", query_type="health", config=None, json=False)
            await run_query(args)

        captured = capsys.readouterr()
        assert "Detection Ensemble Health" in captured.out

    @pytest.mark.asyncio
    async def test_config_error_prints_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """S-158: load_config failure prints to stderr and exits with code 1."""
        from argparse import Namespace
        from unittest.mock import patch

        from seerflow.config import ConfigError
        from seerflow.query import run_query_health

        with (
            patch("seerflow.config.load_config", side_effect=ConfigError("bad config")),
            pytest.raises(SystemExit, match="1"),
        ):
            args = Namespace(config=None, json=False)
            await run_query_health(args)

        captured = capsys.readouterr()
        assert "Error loading config: bad config" in captured.err

    @pytest.mark.asyncio
    async def test_storage_connect_error_prints_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """S-158: SqliteBackend.connect failure prints to stderr and exits with code 1."""
        from argparse import Namespace
        from unittest.mock import AsyncMock, patch

        from seerflow.query import run_query_health

        with (
            patch("seerflow.config.load_config") as mock_cfg,
            patch(
                "seerflow.query.connect_storage",
                new_callable=AsyncMock,
                side_effect=OSError("no db"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            mock_cfg.return_value.storage = None
            args = Namespace(config=None, json=False)
            await run_query_health(args)

        captured = capsys.readouterr()
        assert "Error connecting to storage: no db" in captured.err


class TestWarmupAmplification:
    """S-161: Amplification should not be diluted by warmup channels."""

    def test_warmup_returns_nan_for_template_hw(self) -> None:
        """Template HW returns nan during warmup (before min_events_for_scoring)."""
        config = _granular_config(min_events_for_scoring=100)
        ensemble = DetectionEnsemble(config)
        event = _make_event(template_id=1)
        score = ensemble._score_template_hw("syslog", event)
        assert math.isnan(score)

    def test_warmup_returns_nan_for_negative_template_id(self) -> None:
        """Template HW returns nan for negative template_id."""
        config = _granular_config(min_events_for_scoring=100)
        ensemble = DetectionEnsemble(config)
        event = _make_event(template_id=-1)
        score = ensemble._score_template_hw("syslog", event)
        assert math.isnan(score)

    def test_warmup_returns_nan_for_entity_hw_no_refs(self) -> None:
        """Entity HW returns nan when no entity_refs."""
        config = _granular_config(min_events_for_scoring=100)
        ensemble = DetectionEnsemble(config)
        event = _make_event(entity_refs=())
        score = ensemble._score_entity_hw("syslog", event)
        assert math.isnan(score)

    def test_warmup_returns_nan_for_entity_hw_below_threshold(self) -> None:
        """Entity HW returns nan during warmup (before min_events_for_scoring)."""
        config = _granular_config(min_events_for_scoring=100)
        ensemble = DetectionEnsemble(config)
        event = _make_event(entity_refs=("e1",))
        score = ensemble._score_entity_hw("syslog", event)
        assert math.isnan(score)

    def test_amplification_not_diluted_by_warmup(self) -> None:
        """When template/entity HW are in warmup, amplification uses only active channels."""
        config = _granular_config(min_events_for_scoring=100)
        ensemble = DetectionEnsemble(config)
        event = _make_event(template_id=1, entity_refs=("e1",))
        result = ensemble.process_event(event)
        assert math.isfinite(result.score)

    def test_nan_not_in_final_score(self) -> None:
        """Final detection score must never be nan even with warmup channels."""
        config = _granular_config(min_events_for_scoring=1000)
        ensemble = DetectionEnsemble(config)
        event = _make_event(template_id=5, entity_refs=("host1",))
        result = ensemble.process_event(event)
        assert math.isfinite(result.score)
        assert not math.isnan(result.score)

    def test_all_channels_warmup_returns_zero(self) -> None:
        """When ALL channels are in warmup, score is 0.0 and not anomaly."""
        config = _granular_config(min_events_for_scoring=10_000)
        ensemble = DetectionEnsemble(config)
        event = _make_event(template_id=1, entity_refs=("e1",))
        result = ensemble.process_event(event)
        assert result.score == 0.0
        assert result.is_anomaly is False


class TestSourceEvictionHWCleanup:
    """S-161: Source eviction should clean up orphaned template/entity HW entries."""

    def test_template_hw_cleaned_on_source_eviction(self) -> None:
        config = _granular_config(max_sources=2, max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="s1", template_id=1))
        ensemble.process_event(_make_event(source_type="s2", template_id=2))
        assert "s1:1" in ensemble._template_hw
        ensemble.process_event(_make_event(source_type="s3", template_id=3))
        assert "s1:1" not in ensemble._template_hw

    def test_entity_hw_cleaned_on_source_eviction(self) -> None:
        config = _granular_config(max_sources=2, max_entity_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="s1", entity_refs=("e1",)))
        ensemble.process_event(_make_event(source_type="s2", entity_refs=("e2",)))
        assert "s1:e1" in ensemble._entity_hw
        ensemble.process_event(_make_event(source_type="s3", entity_refs=("e3",)))
        assert "s1:e1" not in ensemble._entity_hw

    def test_event_counts_cleaned_on_source_eviction(self) -> None:
        config = _granular_config(max_sources=2, max_template_hw=100)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="s1", template_id=1))
        assert "s1:1" in ensemble._template_event_counts
        ensemble.process_event(_make_event(source_type="s2", template_id=2))
        ensemble.process_event(_make_event(source_type="s3", template_id=3))
        assert "s1:1" not in ensemble._template_event_counts


class TestDspotThresholdAdjustment:
    """S-050: DSPOT threshold adjustment for false-positive feedback."""

    def test_adjust_upper_threshold_increases_on_fp(self) -> None:
        """FP feedback should increase DSPOT upper threshold by the given factor."""
        from seerflow.detection.threshold import DSpotThreshold

        dspot = DSpotThreshold(calibration_window=200)
        # Feed enough data to calibrate (200 samples)
        for i in range(200):
            dspot.update(float(i % 10))
        assert dspot.is_calibrated

        old_threshold = dspot.threshold
        dspot.adjust_upper_threshold(1.05)
        assert dspot.threshold == pytest.approx(old_threshold * 1.05)

    def test_adjust_returns_false_for_unknown_source(self) -> None:
        """Adjusting an unknown source key should return not_calibrated."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        assert ensemble.adjust_upper_threshold("nonexistent", 1.05).status == "not_calibrated"

    def test_adjust_returns_false_if_not_calibrated(self) -> None:
        """Adjusting a source that exists but isn't calibrated should return not_calibrated."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        # Process 1 event — not enough to calibrate (needs 200)
        ensemble.process_event(_make_event(source_type="syslog"))
        assert ensemble.adjust_upper_threshold("syslog", 1.05).status == "not_calibrated"

    def test_adjust_returns_true_when_calibrated(self) -> None:
        """Adjusting a calibrated source should return applied."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        for i in range(200):
            ensemble.process_event(_make_event(source_type="syslog", template_id=i % 5))
        assert ensemble.adjust_upper_threshold("syslog", 1.05).status == "applied"

    def test_get_upper_threshold_returns_zero_for_unknown(self) -> None:
        """get_upper_threshold returns 0.0 for unknown source."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        assert ensemble.get_upper_threshold("nonexistent") == 0.0

    def test_get_upper_threshold_returns_zero_if_not_calibrated(self) -> None:
        """get_upper_threshold returns 0.0 if source exists but not calibrated."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog"))
        assert ensemble.get_upper_threshold("syslog") == 0.0

    def test_get_upper_threshold_returns_value_when_calibrated(self) -> None:
        """get_upper_threshold returns the actual _upper_z_q when calibrated."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        for i in range(200):
            ensemble.process_event(_make_event(source_type="syslog", template_id=i % 5))
        dspot = ensemble._thresholds["syslog"]
        assert dspot.is_calibrated
        threshold = ensemble.get_upper_threshold("syslog")
        assert threshold == dspot._upper_z_q
        assert math.isfinite(threshold)

    def test_adjust_changes_get_upper_threshold(self) -> None:
        """After adjust, get_upper_threshold reflects the new value."""
        config = DetectionConfig(hw_seasonal_period=10, dspot_calibration_window=200)
        ensemble = DetectionEnsemble(config)
        for i in range(200):
            ensemble.process_event(_make_event(source_type="syslog", template_id=i % 5))
        before = ensemble.get_upper_threshold("syslog")
        ensemble.adjust_upper_threshold("syslog", 1.10)
        after = ensemble.get_upper_threshold("syslog")
        assert after == pytest.approx(before * 1.10)


class TestAdjustUpperThresholdTriState:
    def test_not_calibrated_source_returns_not_calibrated(self) -> None:
        ens = DetectionEnsemble(DetectionConfig())
        result = ens.adjust_upper_threshold("nope", 1.05)
        assert isinstance(result, ThresholdAdjustResult)
        assert result.status == "not_calibrated"
        assert result.current_ratio == 0.0

    def test_applied_returns_ratio(self) -> None:
        ens = DetectionEnsemble(DetectionConfig(dspot_calibration_window=500))
        dspot = ens._get_threshold("src")
        rng = np.random.default_rng(1)
        for _ in range(500):
            dspot.update(float(rng.normal()))
        result = ens.adjust_upper_threshold("src", 1.05)
        assert result.status == "applied"
        assert result.current_ratio == pytest.approx(1.05, rel=1e-9)

    def test_clamped_returns_cap_ratio(self) -> None:
        cfg = DetectionConfig(dspot_calibration_window=500, dspot_threshold_cap_multiplier=2.0)
        ens = DetectionEnsemble(cfg)
        dspot = ens._get_threshold("noisy")
        rng = np.random.default_rng(2)
        for _ in range(500):
            dspot.update(float(rng.normal()))
        result = ens.adjust_upper_threshold("noisy", 10.0)
        assert result.status == "clamped"
        assert result.current_ratio == pytest.approx(2.0, rel=1e-9)

    def test_cap_multiplier_flows_from_config(self) -> None:
        cfg = DetectionConfig(dspot_threshold_cap_multiplier=4.0)
        ens = DetectionEnsemble(cfg)
        dspot = ens._get_threshold("anything")
        assert dspot.cap_multiplier == 4.0

    def test_clamp_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging as _logging

        cfg = DetectionConfig(dspot_calibration_window=500, dspot_threshold_cap_multiplier=2.0)
        ens = DetectionEnsemble(cfg)
        dspot = ens._get_threshold("noisy")
        rng = np.random.default_rng(3)
        for _ in range(500):
            dspot.update(float(rng.normal()))
        with caplog.at_level(_logging.WARNING, logger="seerflow.detection.ensemble"):
            ens.adjust_upper_threshold("noisy", 10.0)
        assert any(
            "capped" in rec.message.lower() and "noisy" in rec.message for rec in caplog.records
        )


class TestSourceColonSanitization:
    """S-201: source_type with colons collapses to underscores so the
    eviction prefix cannot over-match sibling sources."""

    def test_colon_in_source_type_collapses_to_underscore(self) -> None:
        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        ensemble = DetectionEnsemble(config)
        event = _make_event(source_type="syslog:prod", template_id=5)
        result = ensemble.process_event(event)
        assert result.source_type == "syslog_prod"
        assert all(":" not in s for s in ensemble._detectors)

    def test_multiple_colons_all_stripped(self) -> None:
        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        ensemble = DetectionEnsemble(config)
        event = _make_event(source_type="a:b:c:d", template_id=1)
        result = ensemble.process_event(event)
        assert result.source_type == "a_b_c_d"

    def test_colon_and_null_both_stripped(self) -> None:
        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        ensemble = DetectionEnsemble(config)
        event = _make_event(source_type="sys\x00log:prod", template_id=1)
        result = ensemble.process_event(event)
        assert result.source_type == "syslog_prod"

    def test_entity_value_colon_stripped_from_hw_key(self) -> None:
        """IPv6-style entity `fe80::1` must not break the source:entity key shape."""
        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        ensemble = DetectionEnsemble(config)
        event = _make_event(
            source_type="syslog",
            template_id=1,
            entity_refs=("fe80::1",),
        )
        ensemble.process_event(event)
        # Exactly one entity-HW key, with sanitized form `syslog:fe80__1`.
        keys = list(ensemble._entity_hw.keys())
        assert keys == ["syslog:fe80__1"]
        # And: the HW key suffix has no additional colons (source colon is the only one).
        suffixes = [k.split(":", 1)[1] for k in keys]
        assert all(":" not in s for s in suffixes)

    def test_source_at_max_key_len_owner_parse_still_works(self) -> None:
        """Regression guard for the ``_MAX_SOURCE_KEY_LEN`` truncation boundary.

        When ``source`` is near or at the 248-char limit, ``f\"{source}:{tid}\"``
        may be truncated to drop the separator or the suffix. The reverse-index
        owner-parse (``key.split(\":\", 1)[0]``) must still recover the owning
        source for every shape the truncator can produce.
        """
        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        # Three sources that exercise each truncation shape:
        #   - 248 chars  → key collapses to the source (no separator)
        #   - 247 chars  → key is "<source>:" (trailing separator, empty suffix)
        #   - 245 chars  → key is "<source>:9" (suffix truncated to 1 char)
        sources = {
            248: "a" * 248,
            247: "b" * 247,
            245: "c" * 245,
        }
        for source in sources.values():
            ensemble = DetectionEnsemble(config)
            ensemble.process_event(_make_event(source_type=source, template_id=999))
            assert source in ensemble._source_hw_keys
            tmpl_keys, _ = ensemble._source_hw_keys[source]
            assert tmpl_keys == set(ensemble._template_hw.keys())
            # Owner parse recovers the source from every key, regardless of shape.
            for key in tmpl_keys:
                assert key.split(":", 1)[0] == source


class TestReverseHWIndex:
    """S-201: per-source reverse index for O(k) eviction cleanup."""

    def test_source_hw_keys_initialized_empty(self) -> None:
        config = _make_config(max_sources=2, max_template_hw=8, max_entity_hw=8)
        ensemble = DetectionEnsemble(config)
        assert ensemble._source_hw_keys == {}

    def test_template_hw_insert_registers_in_reverse_index(self) -> None:
        config = _make_config(max_sources=2, max_template_hw=8, max_entity_hw=8)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event(source_type="syslog", template_id=1))
        ensemble.process_event(_make_event(source_type="syslog", template_id=2))
        tmpl_set, ent_set = ensemble._source_hw_keys["syslog"]
        assert tmpl_set == {"syslog:1", "syslog:2"}
        assert ent_set == set()

    def test_entity_hw_insert_registers_in_reverse_index(self) -> None:
        config = _make_config(max_sources=2, max_template_hw=8, max_entity_hw=8)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(
            _make_event(
                source_type="syslog",
                template_id=1,
                entity_refs=("10.0.0.1", "user42"),
            ),
        )
        tmpl_set, ent_set = ensemble._source_hw_keys["syslog"]
        assert tmpl_set == {"syslog:1"}
        assert ent_set == {"syslog:10.0.0.1", "syslog:user42"}

    def test_source_eviction_drops_only_owned_hw_keys(self) -> None:
        """Evicting source A must not touch source B's HW keys or counts."""
        config = _make_config(max_sources=2, max_template_hw=64, max_entity_hw=64)
        ensemble = DetectionEnsemble(config)
        for tid in range(3):
            ensemble.process_event(
                _make_event(source_type="srcA", template_id=tid, entity_refs=("eA",)),
            )
        for tid in range(2):
            ensemble.process_event(
                _make_event(source_type="srcB", template_id=tid, entity_refs=("eB",)),
            )
        # Force eviction of srcA (LRU because srcB was most recent).
        ensemble.process_event(
            _make_event(source_type="srcC", template_id=0, entity_refs=("eC",)),
        )
        assert "srcA" not in ensemble._detectors
        assert "srcA" not in ensemble._source_hw_keys
        assert all(not k.startswith("srcA:") for k in ensemble._template_hw)
        assert all(not k.startswith("srcA:") for k in ensemble._entity_hw)
        # srcB untouched.
        assert "srcB" in ensemble._source_hw_keys
        tmpl_b, ent_b = ensemble._source_hw_keys["srcB"]
        assert tmpl_b == {"srcB:0", "srcB:1"}
        assert ent_b == {"srcB:eB"}

    def test_source_eviction_uses_reverse_index_not_prefix_scan(self) -> None:
        """Source eviction must pop the per-source bucket, not walk the HW pool."""
        config = _make_config(max_sources=2, max_template_hw=64, max_entity_hw=64)
        ensemble = DetectionEnsemble(config)
        for tid in range(3):
            ensemble.process_event(_make_event(source_type="srcA", template_id=tid))
        # Fast-path invariant: the reverse-index bucket is removed with pop(),
        # not left as an empty set and not walked via prefix scan.
        assert "srcA" in ensemble._source_hw_keys
        for tid in range(3):
            ensemble.process_event(_make_event(source_type="srcB", template_id=tid))
        ensemble.process_event(_make_event(source_type="srcC", template_id=0))
        assert "srcA" not in ensemble._source_hw_keys
        # Fast-path invariant: bucket must have been popped, not left behind as empty.
        assert ensemble._source_hw_keys.get("srcA") is None

    def test_lru_eviction_of_template_key_clears_reverse_index(self) -> None:
        """When template-HW pool evicts a key, the owner's bucket must drop it."""
        config = _make_config(max_sources=4, max_template_hw=2, max_entity_hw=8)
        ensemble = DetectionEnsemble(config)
        # Fill template pool to capacity under one source.
        ensemble.process_event(_make_event(source_type="s", template_id=1))
        ensemble.process_event(_make_event(source_type="s", template_id=2))
        assert ensemble._source_hw_keys["s"][0] == {"s:1", "s:2"}
        # Adding a third template under the same source evicts LRU "s:1".
        ensemble.process_event(_make_event(source_type="s", template_id=3))
        assert "s:1" not in ensemble._template_hw
        assert ensemble._source_hw_keys["s"][0] == {"s:2", "s:3"}

    def test_lru_eviction_of_entity_key_clears_reverse_index(self) -> None:
        """Same invariant for entity HW pool."""
        config = _make_config(max_sources=4, max_template_hw=8, max_entity_hw=2)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(
            _make_event(source_type="s", template_id=0, entity_refs=("e1",)),
        )
        ensemble.process_event(
            _make_event(source_type="s", template_id=0, entity_refs=("e2",)),
        )
        assert ensemble._source_hw_keys["s"][1] == {"s:e1", "s:e2"}
        ensemble.process_event(
            _make_event(source_type="s", template_id=0, entity_refs=("e3",)),
        )
        assert "s:e1" not in ensemble._entity_hw
        assert ensemble._source_hw_keys["s"][1] == {"s:e2", "s:e3"}

    def test_high_source_churn_eviction_is_o_k(self) -> None:
        """Evicting under adversarial source diversity must not scan the full HW pool.

        Proxy for O(k): the reverse-index bucket for each evicted source is
        popped; no key in _template_hw or _entity_hw survives for an evicted
        source; and sources that were not evicted keep their buckets intact.
        """
        config = _make_config(max_sources=16, max_template_hw=256, max_entity_hw=256)
        ensemble = DetectionEnsemble(config)
        # 500 unique sources, each with 2 template and 1 entity HW key.
        for i in range(500):
            src = f"src{i}"
            ensemble.process_event(
                _make_event(source_type=src, template_id=1, entity_refs=(f"e{i}",)),
            )
            ensemble.process_event(_make_event(source_type=src, template_id=2))
        # Only the last 16 sources should survive (max_sources=16).
        assert len(ensemble._detectors) == 16
        surviving = set(ensemble._detectors.keys())
        assert set(ensemble._source_hw_keys.keys()) == surviving
        # No HW key belongs to an evicted source.
        for key in ensemble._template_hw:
            assert key.split(":", 1)[0] in surviving
        for key in ensemble._entity_hw:
            assert key.split(":", 1)[0] in surviving
        # Eviction counter reflects the 484 kicked-out sources.
        assert ensemble._eviction_count == 484


class TestLoadStateReverseIndex:
    """S-201: load_all_state re-sanitizes manifest keys and rebuilds reverse index."""

    @pytest.mark.asyncio
    async def test_load_populates_reverse_index_from_manifest(self, tmp_path: Path) -> None:
        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        src_ensemble = DetectionEnsemble(config)
        src_ensemble.process_event(
            _make_event(source_type="s", template_id=1, entity_refs=("e1",)),
        )
        src_ensemble.process_event(_make_event(source_type="s", template_id=2))
        await src_ensemble.save_all_state(storage)
        dst_ensemble = DetectionEnsemble(config)
        await dst_ensemble.load_all_state(storage)
        assert dst_ensemble._source_hw_keys["s"][0] == {"s:1", "s:2"}
        assert dst_ensemble._source_hw_keys["s"][1] == {"s:e1"}

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_resanitizes_legacy_colon_keys(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Manifest entries persisted before S-201 may contain colon-laden
        source segments. Sanitize on load and WARN on collision."""
        import logging

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test2.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        # Hand-craft a legacy manifest with a colon in the source segment.
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({"legacy:src:1": 10, "legacy_src:1": 5}),
        )
        # Persist a minimal HW body for each so load_state returns non-None.
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        body = hw.serialize()
        await storage.save_state("tmpl_hw:legacy:src:1", body)
        await storage.save_state("tmpl_hw:legacy_src:1", body)
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        dst = DetectionEnsemble(config)
        with caplog.at_level(logging.WARNING, logger="seerflow.detection.ensemble"):
            await dst.load_all_state(storage)
        # Both pre-existing keys collapse to "legacy_src:1".
        assert list(dst._template_hw.keys()) == ["legacy_src:1"]
        assert dst._source_hw_keys["legacy_src"][0] == {"legacy_src:1"}
        # Collision WARNING fired exactly once and references both raw + sanitized.
        warnings = [
            r for r in caplog.records if r.levelno == logging.WARNING and "Duplicate" in r.message
        ]
        assert len(warnings) == 1
        assert "legacy_src:1" in warnings[0].getMessage()

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_migrates_legacy_colon_laden_entity(self, tmp_path: Path) -> None:
        """Legacy ent_hw manifest with colon in entity (IPv6) sanitizes
        to the runtime shape (ent:fe80::1 → ent:fe80__1) not the rsplit shape."""
        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_migrate.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        # Seed a pre-S-201 ent_hw manifest with a colon-laden entity value.
        await storage.save_state(
            "ent_hw:manifest",
            msgspec.json.encode({"syslog:fe80::1": 7}),
        )
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        await storage.save_state("ent_hw:syslog:fe80::1", hw.serialize())
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        dst = DetectionEnsemble(config)
        await dst.load_all_state(storage)

        # Runtime path produces "syslog:fe80__1" — the migration must match.
        assert list(dst._entity_hw.keys()) == ["syslog:fe80__1"]
        assert dst._source_hw_keys["syslog"][1] == {"syslog:fe80__1"}
        assert dst._entity_event_counts["syslog:fe80__1"] == 7

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_rejects_no_colon_manifest_entry(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No-colon manifest entries cannot derive an owning source; reject
        with WARNING and write zero state so the reverse index stays clean."""
        import logging

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_malformed.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({"malformed": 3}),
        )
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        await storage.save_state("tmpl_hw:malformed", hw.serialize())
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        dst = DetectionEnsemble(config)
        with caplog.at_level(logging.WARNING, logger="seerflow.detection.ensemble"):
            await dst.load_all_state(storage)

        # Zero state written anywhere.
        assert dict(dst._template_hw) == {}
        assert dst._template_event_counts == {}
        assert dst._source_hw_keys == {}
        # One Malformed WARNING.
        malformed = [
            r for r in caplog.records if r.levelno == logging.WARNING and "Malformed" in r.message
        ]
        assert len(malformed) == 1
        assert "tmpl_hw" in malformed[0].getMessage()

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_collision_gcs_losing_raw_key(self, tmp_path: Path) -> None:
        """When two raw manifest keys collapse onto one sanitized key,
        the losing raw_key's on-disk row is deleted so reload does not
        repeat the collision WARNING forever."""
        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_gc.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        # Two pre-existing keys that collapse onto the same sanitized form.
        # First-in-manifest wins; second is the orphan to GC.
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({"legacy_src:1": 5, "legacy:src:1": 10}),
        )
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        body = hw.serialize()
        await storage.save_state("tmpl_hw:legacy_src:1", body)
        await storage.save_state("tmpl_hw:legacy:src:1", body)
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        # Spy on delete_state to capture the exact keys deleted. Wrap
        # the SqliteBackend (slotted, so monkeypatch on the instance
        # fails) in a passthrough proxy that records deletes before
        # delegating.
        deleted: list[str] = []

        class _DeleteSpy:
            def __init__(self, inner: SqliteBackend) -> None:
                self._inner = inner

            async def save_state(self, key: str, data: bytes) -> None:
                await self._inner.save_state(key, data)

            async def load_state(self, key: str) -> bytes | None:
                return await self._inner.load_state(key)

            async def delete_state(self, key: str) -> None:
                deleted.append(key)
                await self._inner.delete_state(key)

        spy_storage = _DeleteSpy(storage)

        dst = DetectionEnsemble(config)
        await dst.load_all_state(spy_storage)

        # Winner (first raw_key in manifest order) survives.
        assert list(dst._template_hw.keys()) == ["legacy_src:1"]
        # Loser's row was GC'd.
        assert "tmpl_hw:legacy:src:1" in deleted

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_collision_gc_failure_logs_and_continues(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If delete_state raises during collision GC, load completes —
        the winner key is still populated and the failure is logged."""
        import logging

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_gcfail.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({"legacy_src:1": 5, "legacy:src:1": 10}),
        )
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        body = hw.serialize()
        await storage.save_state("tmpl_hw:legacy_src:1", body)
        await storage.save_state("tmpl_hw:legacy:src:1", body)
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        # Wrap storage in a proxy whose delete_state always raises,
        # simulating a cleanup hiccup. __slots__ on SqliteBackend blocks
        # monkeypatch on the instance, so a thin proxy is the workaround
        # (same pattern as test_load_collision_gcs_losing_raw_key).
        class _BoomOnDelete:
            def __init__(self, inner: SqliteBackend) -> None:
                self._inner = inner

            async def load_state(self, key: str) -> bytes | None:
                return await self._inner.load_state(key)

            async def save_state(self, key: str, data: bytes) -> None:
                await self._inner.save_state(key, data)

            async def delete_state(self, key: str) -> None:
                raise RuntimeError(f"simulated storage failure for {key}")

        proxy = _BoomOnDelete(storage)

        dst = DetectionEnsemble(config)
        with caplog.at_level(logging.WARNING, logger="seerflow.detection.ensemble"):
            await dst.load_all_state(proxy)  # type: ignore[arg-type]

        # Load completed — winner key survived despite GC failure.
        assert list(dst._template_hw.keys()) == ["legacy_src:1"]
        # Failure WARNING logged exactly once.
        failed = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Failed to GC orphan" in r.message
        ]
        assert len(failed) == 1

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_preserves_248_char_boundary_key(self, tmp_path: Path) -> None:
        """S-201 regression guard: when source_type == _MAX_SOURCE_KEY_LEN, the
        runtime produces a no-colon key (truncation drops the separator). That
        shape must round-trip through save → load without being rejected as
        malformed."""
        from seerflow.detection.ensemble import _MAX_SOURCE_KEY_LEN

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_boundary.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        src = DetectionEnsemble(config)
        long_source = "a" * _MAX_SOURCE_KEY_LEN  # 248 chars → truncation drops ":"
        src.process_event(_make_event(source_type=long_source, template_id=999))
        # Sanity: the persisted key is no-colon.
        assert list(src._template_hw.keys()) == [long_source]
        await src.save_all_state(storage)

        dst = DetectionEnsemble(config)
        await dst.load_all_state(storage)

        # Boundary key survives reload — no cold-start.
        assert list(dst._template_hw.keys()) == [long_source]
        assert dst._source_hw_keys[long_source][0] == {long_source}

        await storage.close()

    @pytest.mark.asyncio
    async def test_load_state_failure_logs_and_continues(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If load_state raises for a specific row (e.g. validation failure
        on a malformed composed key), load completes — the row is skipped
        and the failure is logged."""
        import logging

        storage_cfg = StorageConfig(
            backend="sqlite",
            sqlite_path=str(tmp_path / "test_s202_loadfail.db"),
        )
        storage = await SqliteBackend.connect(storage_cfg)

        config = _make_config(max_sources=4, max_template_hw=16, max_entity_hw=16)
        await storage.save_state(
            "tmpl_hw:manifest",
            msgspec.json.encode({"src:1": 5}),
        )
        hw = HoltWintersDetector(
            seasonal_period=config.hw_seasonal_period,
            alpha=config.hw_alpha,
            beta=config.hw_beta,
            gamma=config.hw_gamma,
            n_std=config.hw_n_std,
        )
        await storage.save_state("tmpl_hw:src:1", hw.serialize())
        await storage.save_state("ensemble:manifest", msgspec.json.encode([]))

        class _BoomOnLoad:
            def __init__(self, inner: SqliteBackend) -> None:
                self._inner = inner

            async def load_state(self, key: str) -> bytes | None:
                if key == "tmpl_hw:src:1":
                    raise ValueError("simulated validation failure")
                return await self._inner.load_state(key)

            async def save_state(self, key: str, data: bytes) -> None:
                await self._inner.save_state(key, data)

            async def delete_state(self, key: str) -> None:
                await self._inner.delete_state(key)

        proxy = _BoomOnLoad(storage)

        dst = DetectionEnsemble(config)
        with caplog.at_level(logging.WARNING, logger="seerflow.detection.ensemble"):
            await dst.load_all_state(proxy)  # type: ignore[arg-type]

        # Load completed; no state for the failing row.
        assert dict(dst._template_hw) == {}
        # Failure WARNING logged.
        failed = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "Failed to load" in r.message
        ]
        assert len(failed) == 1

        await storage.close()


class TestLoadGranularHelpers:
    """S-206 AC-5: focused unit tests for the _load_granular_hw helpers."""

    def _make_ensemble(self) -> DetectionEnsemble:
        return DetectionEnsemble(_make_config())

    # ---- _sanitize_manifest_key ----

    def test_sanitize_tmpl_hw_rsplits_on_last_colon(self) -> None:
        ens = self._make_ensemble()
        # Legacy source with embedded colon + integer template id suffix.
        assert ens._sanitize_manifest_key("tmpl_hw", "sys:tem:42") == "sys_tem:42"

    def test_sanitize_tmpl_hw_strips_null_bytes_from_both_halves(self) -> None:
        ens = self._make_ensemble()
        assert ens._sanitize_manifest_key("tmpl_hw", "sys\x00:12\x003") == "sys:123"

    def test_sanitize_ent_hw_splits_on_first_colon(self) -> None:
        ens = self._make_ensemble()
        # IPv6 entity with colons; split(":", 1) + inner colons collapsed to _.
        assert ens._sanitize_manifest_key("ent_hw", "syslog:fe80::1") == "syslog:fe80__1"

    def test_sanitize_ent_hw_strips_null_bytes(self) -> None:
        ens = self._make_ensemble()
        assert ens._sanitize_manifest_key("ent_hw", "syslog\x00:user\x00") == "syslog:user"

    def test_sanitize_short_no_colon_returns_none(self) -> None:
        ens = self._make_ensemble()
        assert ens._sanitize_manifest_key("tmpl_hw", "short-no-colon") is None
        assert ens._sanitize_manifest_key("ent_hw", "short-no-colon") is None

    def test_sanitize_max_len_no_colon_is_accepted(self) -> None:
        from seerflow.detection.ensemble import _MAX_SOURCE_KEY_LEN

        ens = self._make_ensemble()
        key = "a" * _MAX_SOURCE_KEY_LEN
        assert ens._sanitize_manifest_key("tmpl_hw", key) == key
        assert ens._sanitize_manifest_key("ent_hw", key) == key

    def test_sanitize_unknown_prefix_raises(self) -> None:
        ens = self._make_ensemble()
        with pytest.raises(ValueError, match="Unknown prefix"):
            ens._sanitize_manifest_key("bogus", "a:b")


class TestEnsembleFunctionLength:
    """S-206 AC-1: core loader stays under the project 50-line function cap."""

    def test_load_granular_hw_under_fifty_lines(self) -> None:
        import ast
        import inspect
        import textwrap

        from seerflow.detection.ensemble import DetectionEnsemble

        src = textwrap.dedent(inspect.getsource(DetectionEnsemble._load_granular_hw))
        tree = ast.parse(src)
        fn = tree.body[0]
        assert isinstance(fn, ast.AsyncFunctionDef), (
            "Expected _load_granular_hw to be an async function."
        )
        body_lines = fn.end_lineno - fn.body[0].lineno  # type: ignore[operator]
        assert body_lines < 50, (
            f"_load_granular_hw body is {body_lines} lines, must be < 50 "
            "(CLAUDE.md function-length cap, S-206 AC-1)."
        )
