"""Tests for DetectionEnsemble orchestrator."""

from __future__ import annotations

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
        assert 0.0 <= result.score <= 1.0
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
    def test_ensemble_creates_two_detectors(self) -> None:
        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._detectors["syslog"]) == 3

    def test_ensemble_score_averages_two_detectors(self) -> None:
        config = DetectionConfig(
            hst_window_size=50,
            hst_n_trees=10,
            hw_seasonal_period=10,
            dspot_calibration_window=200,
        )
        ensemble = DetectionEnsemble(config)
        result = ensemble.process_event(_make_event())
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0


class TestEnsembleWithCUSUM:
    def test_ensemble_creates_three_detectors(self) -> None:
        from seerflow.config import DetectionConfig
        from seerflow.detection.ensemble import DetectionEnsemble

        config = DetectionConfig(hw_seasonal_period=10)
        ensemble = DetectionEnsemble(config)
        ensemble.process_event(_make_event())
        assert len(ensemble._detectors["syslog"]) == 3

    def test_ensemble_score_with_three_detectors(self) -> None:
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
        assert 0.0 <= result.score <= 1.0
