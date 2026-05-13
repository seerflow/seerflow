"""Bounded LRU + TTL cache for ``RuleSuggestionResult`` (S-100).

Keyed by ``pattern_key``. Single in-process FastAPI app, low cardinality
(one entry per pattern_key the dashboard has reviewed in the last
``ttl_seconds``), explicit invalidation on rule promotion via
``RuleSuggestionService.invalidate``.

Mirrors :class:`seerflow.llm.explanation.cache.ExplanationCache` — same LRU
+ TTL contract, same ``max_entries=0`` disables, same ``asyncio.Lock``
serialisation. Adds a ``delete(pattern_key)`` method because rule
suggestions have an explicit invalidation lifecycle (when the operator
promotes a rule, the cached suggestion is no longer relevant).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.llm.rule_suggestion.result import RuleSuggestionResult


class RuleSuggestionCache:
    """In-memory LRU + TTL cache for drafted Sigma rule suggestions."""

    def __init__(self, *, max_entries: int = 64, ttl_seconds: int = 21_600) -> None:
        if max_entries < 0:
            msg = f"max_entries must be >= 0, got {max_entries}"
            raise ValueError(msg)
        if ttl_seconds < 1:
            msg = f"ttl_seconds must be >= 1, got {ttl_seconds}"
            raise ValueError(msg)
        self._max_entries = int(max_entries)
        self._ttl_seconds = int(ttl_seconds)
        self._store: OrderedDict[str, tuple[RuleSuggestionResult, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._store)

    async def get(self, pattern_key: str) -> RuleSuggestionResult | None:
        """Return a cached entry (``cached=True``) or ``None`` on miss/expiry."""
        async with self._lock:
            entry = self._store.get(pattern_key)
            if entry is None:
                return None
            result, inserted_at = entry
            now = time.monotonic()
            if now - inserted_at > self._ttl_seconds:
                # Expired — prune and report miss.
                del self._store[pattern_key]
                return None
            # LRU bump.
            self._store.move_to_end(pattern_key)
            return replace(result, cached=True, latency_ms=0.0)

    async def put(self, pattern_key: str, result: RuleSuggestionResult) -> None:
        """Store ``result`` under ``pattern_key``. Evicts LRU on overflow.

        When ``max_entries == 0`` the call is a no-op so the cache layer
        can be configured off without touching service-level code paths.
        """
        if self._max_entries == 0:
            return
        async with self._lock:
            now = time.monotonic()
            if pattern_key in self._store:
                self._store.move_to_end(pattern_key)
            self._store[pattern_key] = (result, now)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)  # evict LRU

    async def delete(self, pattern_key: str) -> None:
        """Remove a single entry. Idempotent; never raises.

        Used by ``RuleSuggestionService.invalidate`` after the operator
        promotes a rule so the dashboard does not keep suggesting a
        pattern that is now codified.
        """
        async with self._lock:
            self._store.pop(pattern_key, None)

    async def clear(self) -> None:
        """Remove all entries."""
        async with self._lock:
            self._store.clear()
