"""Streaming biDSPOT auto-threshold — bidirectional EVT-based anomaly quantile.

Custom implementation based on Siffer et al. (KDD 2017). Uses
scipy.stats.genpareto for GPD fitting. Detects both upper anomalies
(spikes, novel errors) and lower anomalies (silence, drops).

Replaces ads-evt which has a non-functional streaming API on Python 3.13.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

import msgspec
import numpy as np
from scipy.stats import genpareto

_log = logging.getLogger(__name__)

_MAX_EXCESSES = 10_000
_DEFAULT_CAP_MULTIPLIER = 5.0  # operator-feedback threshold cap; see S-169


class _TailState(msgspec.Struct):
    """State for one tail (upper or lower) of the biDSPOT threshold."""

    threshold: float
    z_q: float | None
    excesses: list[float]
    n_exceed: int


class _BiDSpotState(msgspec.Struct):
    """Typed state for safe deserialization."""

    calibration_window: int
    risk_level: float
    initial_percentile: int
    upper: _TailState
    lower: _TailState
    n_total: int
    calibrated: bool
    calibrated_upper_z_q: float | None = None


@dataclass(frozen=True, slots=True)
class ThresholdResult:
    """Result from a threshold check.

    ``anomaly_direction`` is ``"upper"`` for spike anomalies,
    ``"lower"`` for drop anomalies, or ``None`` if not anomalous.
    """

    is_anomaly: bool
    upper_threshold: float
    lower_threshold: float
    score: float
    anomaly_direction: Literal["upper", "lower"] | None = None


class DSpotThreshold:
    """Streaming biDSPOT auto-threshold with bidirectional EVT anomaly detection.

    During calibration (first ``calibration_window`` scores), all scores
    are collected and no anomalies are flagged. After calibration:

    1. Upper threshold at ``initial_percentile`` (default 98th)
    2. Lower threshold at ``100 - initial_percentile`` (default 2nd)
    3. GPD fitted to upper excesses and lower deficits independently
    4. Each new score: flag as anomaly if > upper z_q or < lower z_q

    Only safe to serialize after calibration (``is_calibrated == True``).
    Pre-calibration scores are not persisted.
    """

    __slots__ = (
        "_calibrated",
        "_calibrated_upper_z_q",
        "_calibration_window",
        "_cap_multiplier",
        "_initial_percentile",
        "_lower_excesses",
        "_lower_n_exceed",
        "_lower_threshold",
        "_lower_z_q",
        "_n_total",
        "_risk_level",
        "_scores",
        "_upper_excesses",
        "_upper_n_exceed",
        "_upper_threshold",
        "_upper_z_q",
    )

    def __init__(
        self,
        *,
        calibration_window: int = 1000,
        risk_level: float = 0.0001,
        initial_percentile: int = 98,
        cap_multiplier: float = _DEFAULT_CAP_MULTIPLIER,
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
        if not math.isfinite(cap_multiplier) or cap_multiplier <= 1.0:
            msg = f"cap_multiplier must be finite and > 1.0, got {cap_multiplier}"
            raise ValueError(msg)
        self._calibration_window = calibration_window
        self._risk_level = risk_level
        self._initial_percentile = initial_percentile
        self._cap_multiplier = cap_multiplier
        self._calibrated_upper_z_q: float = 0.0
        self._scores: list[float] = []
        # Upper tail
        self._upper_threshold: float = 0.0
        self._upper_z_q: float = float("inf")
        self._upper_excesses: list[float] = []
        self._upper_n_exceed: int = 0
        # Lower tail
        self._lower_threshold: float = 0.0
        self._lower_z_q: float = float("-inf")
        self._lower_excesses: list[float] = []
        self._lower_n_exceed: int = 0
        # Shared
        self._n_total: int = 0
        self._calibrated: bool = False

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    @property
    def threshold(self) -> float:
        """Upper anomaly threshold (z_q). For lower, use ``lower_threshold``."""
        return self._upper_z_q

    @property
    def lower_threshold(self) -> float:
        """Lower anomaly threshold (z_q)."""
        return self._lower_z_q

    @property
    def calibrated_upper_z_q(self) -> float:
        """Upper-tail threshold captured at calibration time. 0.0 if not calibrated."""
        return self._calibrated_upper_z_q

    @property
    def cap_multiplier(self) -> float:
        """Maximum allowed cumulative growth of upper_z_q over calibrated baseline."""
        return self._cap_multiplier

    def adjust_upper_threshold(self, factor: float) -> tuple[bool, float]:
        """Multiply the upper anomaly threshold by *factor* (must be > 0).

        Clamps the result so that ``upper_z_q`` never exceeds
        ``calibrated_upper_z_q * cap_multiplier``.

        Returns ``(was_clamped, current_ratio)`` where ``current_ratio`` is
        the resulting ``upper_z_q / calibrated_upper_z_q`` after the call.
        If the threshold is not yet calibrated, no-op and returns
        ``(False, 0.0)``.
        """
        if factor <= 0 or not math.isfinite(factor):
            msg = f"factor must be finite and > 0, got {factor}"
            raise ValueError(msg)
        if not self._calibrated or self._calibrated_upper_z_q <= 0:
            return False, 0.0
        proposed = self._upper_z_q * factor
        cap = self._calibrated_upper_z_q * self._cap_multiplier
        if proposed > cap:
            self._upper_z_q = cap
            return True, self._cap_multiplier
        self._upper_z_q = proposed
        ratio = self._upper_z_q / self._calibrated_upper_z_q
        return False, ratio

    def update(self, score: float) -> ThresholdResult:
        """Process a new score. Returns threshold result."""
        if not self._calibrated:
            self._scores.append(score)
            if len(self._scores) >= self._calibration_window:
                self._calibrate()
            return ThresholdResult(
                is_anomaly=False,
                upper_threshold=self._upper_z_q,
                lower_threshold=self._lower_z_q,
                score=score,
            )

        self._n_total += 1

        # Upper anomaly check
        if score > self._upper_z_q:
            return ThresholdResult(
                is_anomaly=True,
                upper_threshold=self._upper_z_q,
                lower_threshold=self._lower_z_q,
                score=score,
                anomaly_direction="upper",
            )

        # Lower anomaly check
        if score < self._lower_z_q:
            return ThresholdResult(
                is_anomaly=True,
                upper_threshold=self._upper_z_q,
                lower_threshold=self._lower_z_q,
                score=score,
                anomaly_direction="lower",
            )

        # Update upper excesses
        if score > self._upper_threshold:
            self._upper_excesses.append(score - self._upper_threshold)
            self._upper_n_exceed += 1
            if len(self._upper_excesses) > _MAX_EXCESSES:
                self._upper_excesses = self._upper_excesses[-_MAX_EXCESSES:]
            if self._upper_n_exceed % 50 == 0:
                self._refit_upper()

        # Update lower excesses (deficits)
        if score < self._lower_threshold:
            self._lower_excesses.append(self._lower_threshold - score)
            self._lower_n_exceed += 1
            if len(self._lower_excesses) > _MAX_EXCESSES:
                self._lower_excesses = self._lower_excesses[-_MAX_EXCESSES:]
            if self._lower_n_exceed % 50 == 0:
                self._refit_lower()

        return ThresholdResult(
            is_anomaly=False,
            upper_threshold=self._upper_z_q,
            lower_threshold=self._lower_z_q,
            score=score,
        )

    def _calibrate(self) -> None:
        """Compute initial thresholds and fit GPD for both tails."""
        arr = np.array(self._scores)
        lower_pct = 100 - self._initial_percentile

        # Upper tail
        self._upper_threshold = float(np.percentile(arr, self._initial_percentile))
        upper_exc = arr[arr > self._upper_threshold] - self._upper_threshold
        self._upper_excesses = upper_exc.tolist()
        self._upper_n_exceed = len(self._upper_excesses)

        # Lower tail
        self._lower_threshold = float(np.percentile(arr, lower_pct))
        lower_exc = self._lower_threshold - arr[arr < self._lower_threshold]
        self._lower_excesses = lower_exc.tolist()
        self._lower_n_exceed = len(self._lower_excesses)

        self._n_total = len(self._scores)
        self._scores = []

        self._refit_upper()
        self._refit_lower()

        if not np.isfinite(self._upper_z_q):
            _log.warning(
                "Upper GPD fit produced no finite threshold (excesses: %d). "
                "Using initial percentile as fallback.",
                len(self._upper_excesses),
            )
            self._upper_z_q = self._upper_threshold

        if not np.isfinite(self._lower_z_q):
            _log.warning(
                "Lower GPD fit produced no finite threshold (deficits: %d). "
                "Using initial percentile as fallback.",
                len(self._lower_excesses),
            )
            self._lower_z_q = self._lower_threshold

        self._calibrated_upper_z_q = self._upper_z_q
        self._calibrated = True

    def _refit_upper(self) -> None:
        """Fit GPD to upper excesses and compute upper z_q."""
        z_q = self._fit_gpd_tail(self._upper_excesses, self._upper_threshold)
        if z_q is not None:
            self._upper_z_q = max(z_q, self._upper_threshold)

    def _refit_lower(self) -> None:
        """Fit GPD to lower deficits and compute lower z_q."""
        z_q = self._fit_gpd_tail(self._lower_excesses, self._lower_threshold)
        if z_q is not None:
            # Lower z_q = lower_threshold - gpd_quantile (mirror of upper)
            self._lower_z_q = min(
                self._lower_threshold - (z_q - self._lower_threshold),
                self._lower_threshold,
            )

    def _fit_gpd_tail(self, excesses: list[float], base_threshold: float) -> float | None:
        """Fit GPD to excesses and return the anomaly quantile, or None on failure."""
        if len(excesses) < 10:
            return None
        exc = np.array(excesses)
        try:
            shape, _loc, scale = genpareto.fit(exc, floc=0)
        except ValueError as exc_info:
            _log.warning("GPD fit failed, keeping previous threshold: %s", exc_info)
            return None
        n_t = len(excesses)
        n = max(self._n_total, 1)
        q = self._risk_level
        if abs(shape) < 1e-10:
            z_q = base_threshold + scale * np.log(n_t / (n * q))
        else:
            z_q = base_threshold + (scale / shape) * ((n_t / (n * q)) ** shape - 1)
        return float(z_q)

    def serialize(self) -> bytes:
        """Serialize threshold state via msgspec JSON.

        Only safe to call after calibration (``is_calibrated == True``).
        Pre-calibration scores are not persisted.
        """
        state = _BiDSpotState(
            calibration_window=self._calibration_window,
            risk_level=self._risk_level,
            initial_percentile=self._initial_percentile,
            upper=_TailState(
                threshold=self._upper_threshold,
                z_q=self._upper_z_q,
                excesses=self._upper_excesses,
                n_exceed=self._upper_n_exceed,
            ),
            lower=_TailState(
                threshold=self._lower_threshold,
                z_q=self._lower_z_q,
                excesses=self._lower_excesses,
                n_exceed=self._lower_n_exceed,
            ),
            n_total=self._n_total,
            calibrated=self._calibrated,
            calibrated_upper_z_q=self._calibrated_upper_z_q,
        )
        return msgspec.json.encode(state)

    @classmethod
    def deserialize(cls, data: bytes) -> DSpotThreshold:
        """Restore threshold state from msgspec JSON bytes.

        Older blobs lacking ``calibrated_upper_z_q`` are handled gracefully:
        the field is seeded from the current ``upper_z_q`` and an INFO
        message is logged.
        """
        state = msgspec.json.decode(data, type=_BiDSpotState)
        obj = cls.__new__(cls)
        obj._calibration_window = state.calibration_window
        obj._risk_level = state.risk_level
        obj._initial_percentile = state.initial_percentile
        obj._cap_multiplier = _DEFAULT_CAP_MULTIPLIER
        obj._upper_threshold = state.upper.threshold
        obj._upper_z_q = state.upper.z_q if state.upper.z_q is not None else float("inf")
        obj._upper_excesses = state.upper.excesses
        obj._upper_n_exceed = state.upper.n_exceed
        obj._lower_threshold = state.lower.threshold
        obj._lower_z_q = state.lower.z_q if state.lower.z_q is not None else float("-inf")
        obj._lower_excesses = state.lower.excesses
        obj._lower_n_exceed = state.lower.n_exceed
        obj._n_total = state.n_total
        obj._calibrated = state.calibrated
        obj._scores = []
        if state.calibrated_upper_z_q is None:
            _log.info(
                "Legacy DSPOT state detected — using current upper_z_q as baseline"
            )
            obj._calibrated_upper_z_q = obj._upper_z_q
        else:
            obj._calibrated_upper_z_q = state.calibrated_upper_z_q
        return obj
