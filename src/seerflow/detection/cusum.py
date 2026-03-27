"""Bidirectional CUSUM change detection for sustained mean shifts.

Tracks event count per 1-minute bucket per source_type. Detects
gradual upward or downward shifts that Holt-Winters may miss.

NOT thread-safe — create one instance per source (the ensemble handles this).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import msgspec.msgpack

if TYPE_CHECKING:
    from seerflow.models import SeerflowEvent

_BUCKET_NS = 60 * 1_000_000_000  # 1 minute in nanoseconds


class CUSUMDetector:
    """Bidirectional CUSUM change detector.

    Implements the ``Detector`` protocol. Tracks event counts in 1-minute
    buckets, standardizes via EMA, and accumulates bidirectional cumulative
    sums. Scores deviation as ``max(g_upper, g_lower) / threshold``.

    Returns ``0.0`` during warmup (first ``warmup_buckets`` buckets).
    Hard-resets cumulative sums when a change point is confirmed (score >= 1.0).
    """

    __slots__ = (
        "_current_bucket",
        "_current_count",
        "_drift",
        "_ema_alpha",
        "_g_lower",
        "_g_upper",
        "_last_score",
        "_running_mean",
        "_running_var",
        "_t",
        "_threshold",
        "_warmup_buckets",
    )

    def __init__(
        self,
        *,
        drift: float = 0.5,
        threshold: float = 5.0,
        ema_alpha: float = 0.1,
        warmup_buckets: int = 30,
    ) -> None:
        if drift <= 0.0:
            msg = f"drift must be positive, got {drift!r}"
            raise ValueError(msg)
        if threshold <= 0.0:
            msg = f"threshold must be positive, got {threshold!r}"
            raise ValueError(msg)
        if not (0.0 < ema_alpha < 1.0):
            msg = f"ema_alpha must be in (0, 1), got {ema_alpha!r}"
            raise ValueError(msg)
        if warmup_buckets < 1:
            msg = f"warmup_buckets must be >= 1, got {warmup_buckets!r}"
            raise ValueError(msg)
        self._drift = drift
        self._threshold = threshold
        self._ema_alpha = ema_alpha
        self._warmup_buckets = warmup_buckets

        self._g_upper: float = 0.0
        self._g_lower: float = 0.0
        self._running_mean: float = 0.0
        self._running_var: float = 1.0
        self._last_score: float = 0.0
        self._current_bucket: int = -1
        self._current_count: int = 0
        self._t: int = 0

    def score(self, event: SeerflowEvent) -> float:
        """Return the CUSUM change score from the last completed bucket."""
        return self._last_score

    def learn(self, event: SeerflowEvent) -> None:
        """Increment event count for the current bucket; update CUSUM on rollover."""
        bucket = event.timestamp_ns // _BUCKET_NS
        if self._current_bucket == -1:
            self._current_bucket = bucket
            self._current_count = 1
            return
        if bucket == self._current_bucket:
            self._current_count += 1
            return
        if bucket < self._current_bucket:
            return  # Drop late-arriving event
        # Bucket rolled over
        self._update(float(self._current_count))
        # Handle gap buckets
        gap = bucket - self._current_bucket - 1
        for _ in range(min(gap, 100)):
            self._update(0.0)
        self._current_bucket = bucket
        self._current_count = 1

    def _update(self, count: float) -> None:
        """Run one CUSUM update step for a completed bucket."""
        self._t += 1

        if self._t == 1:
            self._running_mean = count
            self._running_var = 1.0
            return

        # Update running stats (EMA)
        prev_mean = self._running_mean
        self._running_mean = self._ema_alpha * count + (1 - self._ema_alpha) * self._running_mean
        self._running_var = (
            self._ema_alpha * (count - prev_mean) ** 2 + (1 - self._ema_alpha) * self._running_var
        )
        running_std = max(math.sqrt(self._running_var), 1e-10)

        if self._t <= self._warmup_buckets:
            self._last_score = 0.0
            return

        # Standardize
        z = (count - self._running_mean) / running_std

        # Bidirectional CUSUM
        self._g_upper = max(0.0, self._g_upper + z - self._drift)
        self._g_lower = max(0.0, self._g_lower - z - self._drift)

        # Score
        self._last_score = min(max(self._g_upper, self._g_lower) / self._threshold, 1.0)

        # Hard reset on confirmed change point
        if self._last_score >= 1.0:
            self._g_upper = 0.0
            self._g_lower = 0.0
            self._last_score = 0.0

    def serialize(self) -> bytes:
        """Serialize model state to msgpack bytes."""
        state = {
            "drift": self._drift,
            "threshold": self._threshold,
            "ema_alpha": self._ema_alpha,
            "warmup_buckets": self._warmup_buckets,
            "g_upper": self._g_upper,
            "g_lower": self._g_lower,
            "running_mean": self._running_mean,
            "running_var": self._running_var,
            "last_score": self._last_score,
            "current_bucket": self._current_bucket,
            "current_count": self._current_count,
            "t": self._t,
        }
        return msgspec.msgpack.encode(state)

    def deserialize(self, data: bytes) -> None:
        """Restore model state from msgpack bytes."""
        state: dict = msgspec.msgpack.decode(data)  # type: ignore[type-arg]
        self._drift = state["drift"]
        self._threshold = state["threshold"]
        self._ema_alpha = state["ema_alpha"]
        self._warmup_buckets = state["warmup_buckets"]
        self._g_upper = state["g_upper"]
        self._g_lower = state["g_lower"]
        self._running_mean = state["running_mean"]
        self._running_var = state["running_var"]
        self._last_score = state["last_score"]
        self._current_bucket = state["current_bucket"]
        self._current_count = state["current_count"]
        self._t = state["t"]
