"""Tests for DSpotThreshold — streaming biDSPOT anomaly threshold."""

from __future__ import annotations

import random

import pytest

from seerflow.detection.threshold import DSpotThreshold, ThresholdResult


class TestThresholdResult:
    """ThresholdResult struct tests."""

    def test_creation_and_fields(self) -> None:
        result = ThresholdResult(
            is_anomaly=True, upper_threshold=3.5, lower_threshold=-1.0, score=4.0
        )
        assert result.is_anomaly is True
        assert result.upper_threshold == 3.5
        assert result.lower_threshold == -1.0
        assert result.score == 4.0
        assert result.anomaly_direction is None

    def test_with_direction(self) -> None:
        result = ThresholdResult(
            is_anomaly=True,
            upper_threshold=3.5,
            lower_threshold=-1.0,
            score=5.0,
            anomaly_direction="upper",
        )
        assert result.anomaly_direction == "upper"

    def test_frozen(self) -> None:
        result = ThresholdResult(
            is_anomaly=False, upper_threshold=1.0, lower_threshold=-1.0, score=0.5
        )
        with pytest.raises(AttributeError):
            result.is_anomaly = True  # type: ignore[misc]


class TestDSpotCalibration:
    """Calibration lifecycle tests."""

    def test_not_calibrated_initially(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        assert ds.is_calibrated is False

    def test_calibrates_after_window(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        rng = random.Random(42)  # noqa: S311
        for _ in range(200):
            ds.update(rng.gauss(0, 1))
        assert ds.is_calibrated is True

    def test_returns_not_anomaly_during_calibration(self) -> None:
        ds = DSpotThreshold(calibration_window=200)
        for i in range(199):
            result = ds.update(float(i))
            assert result.is_anomaly is False

    def test_upper_threshold_set_after_calibration(self) -> None:
        rng = random.Random(42)  # noqa: S311
        ds = DSpotThreshold(calibration_window=500, initial_percentile=80)
        for _ in range(500):
            ds.update(rng.gauss(0, 1))
        assert ds.threshold != float("inf")
        assert ds.threshold > 0

    def test_lower_threshold_set_after_calibration(self) -> None:
        rng = random.Random(42)  # noqa: S311
        ds = DSpotThreshold(calibration_window=500, initial_percentile=80)
        for _ in range(500):
            ds.update(rng.gauss(0, 1))
        assert ds.lower_threshold != float("-inf")
        assert ds.lower_threshold < 0


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
            DSpotThreshold(initial_percentile=100)


def _calibrated_detector() -> DSpotThreshold:
    """Build a calibrated detector from normal Gaussian data."""
    rng = random.Random(42)  # noqa: S311
    ds = DSpotThreshold(calibration_window=500, initial_percentile=80)
    for _ in range(500):
        ds.update(rng.gauss(0, 1))
    assert ds.is_calibrated
    return ds


class TestDSpotAnomalyDetection:
    """Post-calibration anomaly detection tests."""

    def test_normal_scores_low_fp_rate(self) -> None:
        ds = _calibrated_detector()
        rng = random.Random(99)  # noqa: S311
        anomalies = sum(ds.update(rng.gauss(0, 1)).is_anomaly for _ in range(200))
        assert anomalies / 200 < 0.05, f"FP rate {anomalies / 200:.2%} >= 5%"

    def test_upper_extreme_flagged(self) -> None:
        ds = _calibrated_detector()
        result = ds.update(10.0)
        assert result.is_anomaly is True
        assert result.anomaly_direction == "upper"

    def test_lower_extreme_flagged(self) -> None:
        ds = _calibrated_detector()
        result = ds.update(-10.0)
        assert result.is_anomaly is True
        assert result.anomaly_direction == "lower"

    def test_result_contains_correct_score(self) -> None:
        ds = _calibrated_detector()
        result = ds.update(0.42)
        assert result.score == 0.42

    def test_result_has_both_thresholds(self) -> None:
        ds = _calibrated_detector()
        result = ds.update(0.0)
        assert result.upper_threshold > result.lower_threshold


class TestDSpotSerialization:
    """Serialization round-trip tests."""

    def test_serialize_returns_bytes(self) -> None:
        ds = _calibrated_detector()
        data = ds.serialize()
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_round_trip_preserves_state(self) -> None:
        ds = _calibrated_detector()
        data = ds.serialize()
        restored = DSpotThreshold.deserialize(data)
        assert restored.is_calibrated == ds.is_calibrated
        assert restored.threshold == ds.threshold
        assert restored.lower_threshold == ds.lower_threshold
