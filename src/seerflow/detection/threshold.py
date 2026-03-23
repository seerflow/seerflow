"""Streaming DSPOT auto-threshold — EVT-based anomaly quantile.

Custom implementation based on Siffer et al. (KDD 2017). Uses
scipy.stats.genpareto for GPD fitting. Replaces ads-evt which has
a non-functional streaming API on Python 3.13.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import msgspec
import numpy as np
from scipy.stats import genpareto

_log = logging.getLogger(__name__)

_MAX_EXCESSES = 10_000


class _DSpotState(msgspec.Struct):
    """Typed state for safe deserialization."""

    calibration_window: int
    risk_level: float
    initial_percentile: int
    threshold: float
    z_q: float
    excesses: list[float]
    n_total: int
    n_exceed: int
    calibrated: bool


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """Result from a threshold check."""

    is_anomaly: bool
    threshold: float
    score: float


class DSpotThreshold:
    """Streaming DSPOT auto-threshold with EVT-based anomaly detection.

    During calibration (first ``calibration_window`` scores), all scores
    are collected and no anomalies are flagged. After calibration:

    1. Initial threshold ``t`` set at ``initial_percentile`` of calibration data
    2. GPD fitted to excesses (scores above ``t``)
    3. Anomaly quantile ``z_q`` computed for the configured ``risk_level``
    4. Each new score: flag as anomaly if > ``z_q``, update GPD if > ``t``

    Only safe to serialize after calibration (``is_calibrated == True``).
    Pre-calibration scores are not persisted.
    """

    __slots__ = (
        "_calibrated",
        "_calibration_window",
        "_excesses",
        "_initial_percentile",
        "_n_exceed",
        "_n_total",
        "_risk_level",
        "_scores",
        "_threshold",
        "_z_q",
    )

    def __init__(
        self,
        *,
        calibration_window: int = 1000,
        risk_level: float = 0.0001,
        initial_percentile: int = 98,
    ) -> None:
        if calibration_window < 200:
            msg = f"calibration_window must be >= 200, got {calibration_window}"
            raise ValueError(msg)
        if not (0 < risk_level < 1):
            msg = f"risk_level must be in (0, 1), got {risk_level}"
            raise ValueError(msg)
        if not (50 <= initial_percentile <= 99):
            msg = f"initial_percentile must be in [50, 99], got {initial_percentile}"
            raise ValueError(msg)
        self._calibration_window = calibration_window
        self._risk_level = risk_level
        self._initial_percentile = initial_percentile
        self._scores: list[float] = []
        self._threshold: float = 0.0
        self._z_q: float = float("inf")
        self._excesses: list[float] = []
        self._n_total: int = 0
        self._n_exceed: int = 0
        self._calibrated: bool = False

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    @property
    def threshold(self) -> float:
        return self._z_q

    def update(self, score: float) -> ThresholdResult:
        """Process a new score. Returns threshold result."""
        if not self._calibrated:
            self._scores.append(score)
            if len(self._scores) >= self._calibration_window:
                self._calibrate()
            return ThresholdResult(is_anomaly=False, threshold=self._z_q, score=score)

        self._n_total += 1
        if score > self._z_q:
            return ThresholdResult(is_anomaly=True, threshold=self._z_q, score=score)
        if score > self._threshold:
            self._excesses.append(score - self._threshold)
            self._n_exceed += 1
            if len(self._excesses) > _MAX_EXCESSES:
                self._excesses = self._excesses[-_MAX_EXCESSES:]
            if self._n_exceed % 50 == 0:
                self._refit_gpd()
        return ThresholdResult(is_anomaly=False, threshold=self._z_q, score=score)

    def _calibrate(self) -> None:
        """Compute initial threshold and fit GPD after calibration window."""
        arr = np.array(self._scores)
        self._threshold = float(np.percentile(arr, self._initial_percentile))
        excesses = arr[arr > self._threshold] - self._threshold
        self._excesses = excesses.tolist()
        self._n_total = len(self._scores)
        self._n_exceed = len(self._excesses)
        self._scores = []
        self._refit_gpd()
        if not np.isfinite(self._z_q):
            _log.warning(
                "GPD fit produced no finite threshold (excesses: %d). "
                "Using initial percentile threshold as fallback.",
                len(self._excesses),
            )
            self._z_q = self._threshold
        self._calibrated = True

    def _refit_gpd(self) -> None:
        """Fit GPD to excesses and compute anomaly quantile z_q."""
        if len(self._excesses) < 10:
            return
        exc = np.array(self._excesses)
        try:
            shape, _loc, scale = genpareto.fit(exc, floc=0)
        except ValueError as exc_info:
            _log.warning("GPD fit failed, keeping previous threshold: %s", exc_info)
            return
        n_t = len(self._excesses)
        n = max(self._n_total, 1)
        q = self._risk_level
        if abs(shape) < 1e-10:
            z_q = self._threshold + scale * np.log(n_t / (n * q))
        else:
            z_q = self._threshold + (scale / shape) * ((n_t / (n * q)) ** shape - 1)
        z_q = float(z_q)
        # Clamp: threshold must be at or above the initial percentile threshold
        self._z_q = max(z_q, self._threshold)

    def serialize(self) -> bytes:
        """Serialize threshold state via msgspec JSON.

        Only safe to call after calibration (``is_calibrated == True``).
        Pre-calibration scores are not persisted.
        """
        state = _DSpotState(
            calibration_window=self._calibration_window,
            risk_level=self._risk_level,
            initial_percentile=self._initial_percentile,
            threshold=self._threshold,
            z_q=self._z_q,
            excesses=self._excesses,
            n_total=self._n_total,
            n_exceed=self._n_exceed,
            calibrated=self._calibrated,
        )
        return msgspec.json.encode(state)

    @classmethod
    def deserialize(cls, data: bytes) -> DSpotThreshold:
        """Restore threshold state from msgspec JSON bytes."""
        state = msgspec.json.decode(data, type=_DSpotState)
        obj = cls.__new__(cls)
        obj._calibration_window = state.calibration_window
        obj._risk_level = state.risk_level
        obj._initial_percentile = state.initial_percentile
        obj._threshold = state.threshold
        obj._z_q = state.z_q
        obj._excesses = state.excesses
        obj._n_total = state.n_total
        obj._n_exceed = state.n_exceed
        obj._calibrated = state.calibrated
        obj._scores = []
        return obj
