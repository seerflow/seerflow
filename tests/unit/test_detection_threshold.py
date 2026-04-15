"""Tests for DSpotThreshold cap + baseline behavior (S-169)."""

from __future__ import annotations

import logging

import msgspec
import numpy as np
import pytest

from seerflow.detection.threshold import DSpotThreshold


def _calibrate(dspot: DSpotThreshold, seed: int = 0, n: int = 500) -> None:
    rng = np.random.default_rng(seed)
    for _ in range(n):
        dspot.update(float(rng.normal(0.0, 1.0)))
    assert dspot.is_calibrated


class TestCalibratedBaseline:
    def test_baseline_captured_at_calibration(self) -> None:
        dspot = DSpotThreshold(calibration_window=500)
        _calibrate(dspot, seed=1)
        baseline = dspot.calibrated_upper_z_q
        assert baseline > 0
        # right after calibration, z_q == baseline
        assert baseline == pytest.approx(dspot.threshold)

    def test_baseline_uninitialized_before_calibration(self) -> None:
        dspot = DSpotThreshold(calibration_window=500)
        assert dspot.calibrated_upper_z_q == 0.0


class TestAdjustUpperThresholdCap:
    def test_adjust_returns_clamp_info_under_cap(self) -> None:
        dspot = DSpotThreshold(calibration_window=500, cap_multiplier=5.0)
        _calibrate(dspot, seed=2)
        was_clamped, ratio = dspot.adjust_upper_threshold(1.05)
        assert was_clamped is False
        assert ratio == pytest.approx(1.05, rel=1e-9)

    def test_adjust_clamps_at_cap(self) -> None:
        dspot = DSpotThreshold(calibration_window=500, cap_multiplier=2.0)
        _calibrate(dspot, seed=3)
        baseline = dspot.calibrated_upper_z_q
        was_clamped, ratio = dspot.adjust_upper_threshold(10.0)
        assert was_clamped is True
        assert ratio == pytest.approx(2.0, rel=1e-9)
        assert dspot.threshold == pytest.approx(baseline * 2.0, rel=1e-9)

    def test_adjust_cumulative_growth_capped(self) -> None:
        dspot = DSpotThreshold(calibration_window=500, cap_multiplier=2.0)
        _calibrate(dspot, seed=4)
        baseline = dspot.calibrated_upper_z_q
        for _ in range(200):
            dspot.adjust_upper_threshold(1.05)
        assert dspot.threshold == pytest.approx(baseline * 2.0, rel=1e-9)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("inf"), float("nan")])
    def test_adjust_rejects_invalid_factor(self, bad: float) -> None:
        dspot = DSpotThreshold(calibration_window=500)
        _calibrate(dspot, seed=5)
        with pytest.raises(ValueError, match="factor must be finite and > 0"):
            dspot.adjust_upper_threshold(bad)

    def test_adjust_noop_when_not_calibrated(self) -> None:
        dspot = DSpotThreshold(calibration_window=500)
        was_clamped, ratio = dspot.adjust_upper_threshold(1.5)
        assert was_clamped is False
        assert ratio == 0.0


class TestSerializationRoundTrip:
    def test_baseline_survives_serialize_deserialize(self) -> None:
        dspot = DSpotThreshold(calibration_window=500, cap_multiplier=3.0)
        _calibrate(dspot, seed=6)
        dspot.adjust_upper_threshold(1.5)
        baseline = dspot.calibrated_upper_z_q
        restored = DSpotThreshold.deserialize(dspot.serialize())
        assert restored.calibrated_upper_z_q == pytest.approx(baseline, rel=1e-9)

    def test_legacy_blob_populates_baseline_from_current(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Older blobs lack calibrated_upper_z_q; fall back at load and log."""
        dspot = DSpotThreshold(calibration_window=500)
        _calibrate(dspot, seed=7)
        full = msgspec.json.decode(dspot.serialize())
        full.pop("calibrated_upper_z_q", None)
        legacy_bytes = msgspec.json.encode(full)
        with caplog.at_level(logging.INFO, logger="seerflow.detection.threshold"):
            restored = DSpotThreshold.deserialize(legacy_bytes)
        assert restored.calibrated_upper_z_q == restored.threshold
        assert any("legacy dspot state" in rec.message.lower() for rec in caplog.records)
