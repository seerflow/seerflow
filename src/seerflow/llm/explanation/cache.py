"""Bounded LRU + TTL cache for ``ExplanationResult`` (S-071, Task 4).

Keyed by ``alert_id``. Designed for a single in-process FastAPI app
serving the dashboard; cardinality is low (one entry per alert touched
in the last ``ttl_seconds``) and explanations age out anyway.

The cache:

- evicts least-recently-used entries when ``len(cache) > max_entries``;
- prunes entries older than ``ttl_seconds`` on access;
- serialises mutations through an ``asyncio.Lock`` so concurrent
  request handlers cannot corrupt the underlying ``OrderedDict``;
- returns ``ExplanationResult`` instances with ``cached=True`` and
  ``latency_ms=0.0`` on a hit, regardless of what was stored.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.llm.explanation.result import ExplanationResult


class ExplanationCache:
    """In-memory LRU + TTL cache.

    ``max_entries=0`` effectively disables the cache (every ``put`` is a
    no-op; every ``get`` is a miss). The TTL is checked lazily on access.
    """

    def __init__(self, *, max_entries: int = 256, ttl_seconds: int = 3600) -> None:
        if max_entries < 0:
            raise ValueError(f"max_entries must be >= 0, got {max_entries}")
        if ttl_seconds < 1:
            raise ValueError(f"ttl_seconds must be >= 1, got {ttl_seconds}")
        self._max_entries = int(max_entries)
        self._ttl_seconds = int(ttl_seconds)
        self._store: OrderedDict[str, tuple[ExplanationResult, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._store)

    async def get(self, alert_id: str) -> ExplanationResult | None:
        """Return a cached entry (``cached=True``) or ``None`` on miss/expiry."""
        async with self._lock:
            entry = self._store.get(alert_id)
            if entry is None:
                return None
            result, inserted_at = entry
            now = time.monotonic()
            if now - inserted_at > self._ttl_seconds:
                # Expired — prune and report miss.
                del self._store[alert_id]
                return None
            # LRU bump.
            self._store.move_to_end(alert_id)
            return replace(result, cached=True, latency_ms=0.0)

    async def put(self, alert_id: str, result: ExplanationResult) -> None:
        """Store ``result`` under ``alert_id``. Evicts LRU on overflow.

        When ``max_entries == 0`` the call is a no-op so the cache layer
        can be configured off without changing service-level code paths.
        """
        if self._max_entries == 0:
            return
        async with self._lock:
            now = time.monotonic()
            if alert_id in self._store:
                self._store.move_to_end(alert_id)
            self._store[alert_id] = (result, now)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)  # evict LRU

    async def clear(self) -> None:
        """Remove all entries."""
        async with self._lock:
            self._store.clear()
