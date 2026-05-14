"""Rolling per-stage latency reservoir for the health endpoint (S-080).

Feeds ``GET /api/v1/health`` with ``p50``/``p95``/``p99`` per pipeline stage.
Designed to:

- stay O(1) on record (single ``deque.append``);
- bound memory (per-stage ring buffer, hard cap on distinct stage names);
- stay thread-safe across the async event loop and the FastAPI worker that
  reads the snapshot under ``run_in_threadpool``;
- keep snapshot work cheap enough for the 50 ms health budget (FR-047):
  ``statistics.quantiles`` on ≤ 2 048 floats is well under 5 ms.
"""

from __future__ import annotations

import logging
import statistics
import threading
from collections import deque
from typing import Final

__all__ = ["StageLatencyTracker"]

_log = logging.getLogger("seerflow.api.latency")

_DEFAULT_MAXLEN: Final[int] = 2048
_DEFAULT_MAX_STAGES: Final[int] = 16


class StageLatencyTracker:
    """Thread-safe per-stage rolling latency buffer.

    Each stage owns an independent ``collections.deque(maxlen=maxlen)`` of
    raw millisecond samples. Snapshot returns ``{p50, p95, p99, count}`` per
    stage computed from a copy of the buffer under a per-instance lock.
    """

    __slots__ = (
        "_buffers",
        "_lock",
        "_max_stages",
        "_maxlen",
        "_overflow_warned",
    )

    def __init__(
        self,
        maxlen: int = _DEFAULT_MAXLEN,
        max_stages: int = _DEFAULT_MAX_STAGES,
    ) -> None:
        if maxlen < 1:
            msg = f"maxlen must be >= 1, got {maxlen}"
            raise ValueError(msg)
        if max_stages < 1:
            msg = f"max_stages must be >= 1, got {max_stages}"
            raise ValueError(msg)
        self._maxlen = maxlen
        self._max_stages = max_stages
        self._buffers: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._overflow_warned = False

    def record(self, stage: str, elapsed_ms: float) -> None:
        """Append one observation. Silently drops unknown stages over cap.

        Stage names beyond ``max_stages`` are dropped to prevent unbounded
        growth from an accidental high-cardinality dimension. A single
        warning is logged the first time the cap is hit.
        """
        with self._lock:
            buf = self._buffers.get(stage)
            if buf is None:
                if len(self._buffers) >= self._max_stages:
                    if not self._overflow_warned:
                        _log.warning(
                            "StageLatencyTracker: stage cap %d reached, "
                            "dropping further stages (first dropped: %s)",
                            self._max_stages,
                            stage,
                        )
                        self._overflow_warned = True
                    return
                buf = deque(maxlen=self._maxlen)
                self._buffers[stage] = buf
            buf.append(float(elapsed_ms))

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return ``{stage: {p50, p95, p99, count}}`` for non-empty stages.

        Computed under the lock to avoid concurrent mutation during the
        ``list(deque)`` copy. ``statistics.quantiles`` requires ``n >= 2``
        samples — single-sample stages collapse to the observed value.
        """
        snap: dict[str, dict[str, float]] = {}
        with self._lock:
            for stage, buf in self._buffers.items():
                if not buf:
                    continue
                samples = list(buf)
                count = len(samples)
                if count == 1:
                    only = samples[0]
                    snap[stage] = {
                        "p50": only,
                        "p95": only,
                        "p99": only,
                        "count": float(count),
                    }
                    continue
                cuts = statistics.quantiles(samples, n=100, method="inclusive")
                # ``cuts`` has 99 entries; index 49 -> 50th, 94 -> 95th, 98 -> 99th.
                snap[stage] = {
                    "p50": float(cuts[49]),
                    "p95": float(cuts[94]),
                    "p99": float(cuts[98]),
                    "count": float(count),
                }
        return snap
