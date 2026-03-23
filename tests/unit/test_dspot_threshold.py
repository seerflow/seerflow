"""Tests for DSpotThreshold — streaming EVT-based anomaly threshold."""

from __future__ import annotations

import pytest

from seerflow.detection.threshold import DSpotThreshold, ThresholdResult


class TestThresholdResult:
    """ThresholdResult struct tests."""

    def test_creation_and_fields(self) -> None:
        result = ThresholdResult(is_anomaly=True, threshold=3.5, score=4.0)
        assert result.is_anomaly is True
        assert result.threshold == 3.5
        assert result.score == 4.0

    def test_frozen(self) -> None:
        result = ThresholdResult(is_anomaly=False, threshold=1.0, score=0.5)
        with pytest.raises(AttributeError):
            result.is_anomaly = True  # type: ignore[misc]


class TestDSpotCalibration:
    """Calibration lifecycle tests."""

    def test_not_calibrated_initially(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        assert ds.is_calibrated is False

    def test_calibrates_after_window(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        for i in range(200):
            ds.update(float(i))
        assert ds.is_calibrated is True

    def test_returns_not_anomaly_during_calibration(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        for i in range(199):
            result = ds.update(float(i))
            assert result.is_anomaly is False

    def test_threshold_set_after_calibration(self) -> None:
        import random

        rng = random.Random(42)
        ds = DSpotThreshold(calibration_window=500, initial_percentile=80)
        for _ in range(500):
            ds.update(rng.gauss(0, 1))
        assert ds.threshold != float("inf")
        assert ds.threshold > 0


class TestDSpotValidation:
    """Input validation tests."""

    def test_window_too_small(self) -> None:
        with pytest.raises(ValueError, match="calibration_window must be >= 200"):
            DSpotThreshold(calibration_window=199)

    def test_risk_level_zero(self) -> None:
        with pytest.raises(ValueError, match="risk_level must be in"):
            DSpotThreshold(risk_level=0.0)

    def test_risk_level_one(self) -> None:
        with pytest.raises(ValueError, match="risk_level must be in"):
            DSpotThreshold(risk_level=1.0)

    def test_percentile_too_low(self) -> None:
        with pytest.raises(ValueError, match="initial_percentile must be in"):
            DSpotThreshold(initial_percentile=49)

    def test_percentile_too_high(self) -> None:
        with pytest.raises(ValueError, match="initial_percentile must be in"):
            DSpotThreshold(initial_percentile=101)
