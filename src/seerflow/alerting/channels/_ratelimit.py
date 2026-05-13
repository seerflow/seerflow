"""Async token-bucket rate limiter for channel delivery (S-163)."""

from __future__ import annotations

import asyncio
from time import monotonic


class TokenBucket:
    """Refill ``rate_per_second`` tokens up to ``burst``.

    ``acquire`` blocks until a whole token is available, then consumes one.
    Not thread-safe — a single bucket must be driven from one event loop.
    """

    __slots__ = ("_burst", "_last", "_lock", "_rate", "_tokens")

    def __init__(self, rate_per_second: float, burst: int) -> None:
        if rate_per_second <= 0:
            msg = f"rate_per_second must be > 0, got {rate_per_second!r}"
            raise ValueError(msg)
        if burst < 1:
            msg = f"burst must be >= 1, got {burst!r}"
            raise ValueError(msg)
        self._rate = float(rate_per_second)
        self._burst = int(burst)
        self._tokens = float(burst)
        self._last = monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait (if needed) until a token is available, then consume one."""
        async with self._lock:
            while True:
                now = monotonic()
                self._tokens = min(
                    float(self._burst),
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                await asyncio.sleep(deficit / self._rate)
