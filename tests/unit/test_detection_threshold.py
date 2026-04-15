"""Tests for DSpotThreshold cap + baseline behavior (S-169)."""

from __future__ import annotations

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
