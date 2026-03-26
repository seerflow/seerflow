"""Holt-Winters triple exponential smoothing for volume anomaly detection.

Tracks event count per 1-minute bucket per source_type. Learns daily
seasonal patterns and scores deviations from expected volume.

NOT thread-safe — create one instance per source (the ensemble handles this).
"""

from __future__ import annotations

import statistics
from collections import deque
from typing import TYPE_CHECKING

import msgspec.msgpack

if TYPE_CHECKING:
    from seerflow.models import SeerflowEvent

_BUCKET_NS = 60 * 1_000_000_000  # 1 minute in nanoseconds
_MAX_RESIDUALS = 100


class HoltWintersDetector:
    """Online Holt-Winters volume anomaly detector.

    Implements the ``Detector`` protocol. Tracks event counts in 1-minute
    buckets, applies triple exponential smoothing (level + trend + seasonal),
    and scores deviations from predicted volume.

    Returns ``0.0`` during the warmup period (first ``seasonal_period`` buckets).
    """

    __slots__ = (
        "_alpha",
        "_beta",
        "_current_bucket",
        "_current_count",
        "_gamma",
        "_initialized",
        "_last_score",
        "_level",
        "_n_std",
        "_residuals",
        "_seasonal_period",
        "_seasonals",
        "_t",
        "_trend",
    )

    def __init__(
        self,
        *,
        seasonal_period: int = 1440,
        alpha: float = 0.3,
        beta: float = 0.1,
        gamma: float = 0.1,
        n_std: float = 3.0,
    ) -> None:
        if seasonal_period < 2:
            msg = f"seasonal_period must be >= 2, got {seasonal_period!r}"
            raise ValueError(msg)
        for name, val in (("alpha", alpha), ("beta", beta), ("gamma", gamma)):
            if not (0.0 < val < 1.0):
                msg = f"{name} must be in (0, 1), got {val!r}"
                raise ValueError(msg)
        if n_std <= 0.0:
            msg = f"n_std must be positive, got {n_std!r}"
            raise ValueError(msg)
        self._seasonal_period = seasonal_period
        self._alpha = alpha
        self._beta = beta
        self._gamma = gamma
        self._n_std = n_std

        self._level: float = 0.0
        self._trend: float = 0.0
        self._seasonals: list[float] = [0.0] * seasonal_period
        self._residuals: deque[float] = deque(maxlen=_MAX_RESIDUALS)

        self._current_bucket: int = -1
        self._current_count: int = 0
        self._t: int = 0
        self._last_score: float = 0.0
        self._initialized: bool = False

    def score(self, event: SeerflowEvent) -> float:
        """Return the volume anomaly score from the last completed bucket."""
        return self._last_score

    def learn(self, event: SeerflowEvent) -> None:
        """Increment event count for the current bucket; update model on rollover."""
        bucket = event.timestamp_ns // _BUCKET_NS
        if self._current_bucket == -1:
            self._current_bucket = bucket
            self._current_count = 1
            return
        if bucket == self._current_bucket:
            self._current_count += 1
            return
        # Bucket rolled over — process completed bucket(s)
        self._update(float(self._current_count))
        # Handle gap buckets (missed minutes)
        gap = bucket - self._current_bucket - 1
        for _ in range(min(gap, self._seasonal_period)):
            self._update(0.0)
        self._current_bucket = bucket
        self._current_count = 1

    def _update(self, count: float) -> None:
        """Run one Holt-Winters update step for a completed bucket."""
        if not self._initialized:
            self._level = count
            self._initialized = True
            self._t += 1
            return

        idx = self._t % self._seasonal_period

        if self._t < self._seasonal_period:
            # Warmup: accumulate seasonal estimates
            self._seasonals[idx] = count - self._level
            self._level = (self._level * self._t + count) / (self._t + 1)
            self._t += 1
            self._last_score = 0.0
            return

        # Full triple exponential smoothing
        prediction = self._level + self._trend + self._seasonals[idx]
        residual = count - prediction

        prev_level = self._level
        self._level = self._alpha * (count - self._seasonals[idx]) + (1 - self._alpha) * (
            prev_level + self._trend
        )
        self._trend = self._beta * (self._level - prev_level) + (1 - self._beta) * self._trend
        self._seasonals[idx] = (
            self._gamma * (count - prev_level - self._trend)
            + (1 - self._gamma) * self._seasonals[idx]
        )

        self._residuals.append(residual)
        if len(self._residuals) > 1:
            std = statistics.stdev(self._residuals)
            self._last_score = min(abs(residual) / max(self._n_std * std, 1e-10), 1.0)
        else:
            self._last_score = 0.0
        self._t += 1

    def serialize(self) -> bytes:
        """Serialize model state to msgpack bytes."""
        state = {
            "seasonal_period": self._seasonal_period,
            "alpha": self._alpha,
            "beta": self._beta,
            "gamma": self._gamma,
            "n_std": self._n_std,
            "level": self._level,
            "trend": self._trend,
            "seasonals": self._seasonals,
            "residuals": list(self._residuals),
            "current_bucket": self._current_bucket,
            "current_count": self._current_count,
            "t": self._t,
            "last_score": self._last_score,
            "initialized": self._initialized,
        }
        return msgspec.msgpack.encode(state)

    def deserialize(self, data: bytes) -> None:
        """Restore model state from msgpack bytes."""
        state: dict = msgspec.msgpack.decode(data)  # type: ignore[type-arg]
        self._seasonal_period = state["seasonal_period"]
        self._alpha = state["alpha"]
        self._beta = state["beta"]
        self._gamma = state["gamma"]
        self._n_std = state["n_std"]
        self._level = state["level"]
        self._trend = state["trend"]
        self._seasonals = state["seasonals"]
        self._residuals = deque(state["residuals"], maxlen=_MAX_RESIDUALS)
        self._current_bucket = state["current_bucket"]
        self._current_count = state["current_count"]
        self._t = state["t"]
        self._last_score = state["last_score"]
        self._initialized = state["initialized"]
