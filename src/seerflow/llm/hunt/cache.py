"""Bounded LRU + TTL cache for natural language hunt translations (S-072).

Mirrors ``seerflow.llm.explanation.cache.ExplanationCache`` but keyed by the
*normalised* NL query string and stores the *translated filter dict*, not a
result. Storing only the filters keeps event payloads fresh from the
``LogStore`` on every hit — the cache shortcuts only the LLM round trip.

Key normalisation collapses runs of whitespace and lower-cases the query so
``"SSH from external"`` and ``"  ssh   FROM  external"`` map to the same
entry. The cache returns a defensive copy on read so mutations by the caller
cannot corrupt the stored entry.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections import OrderedDict


def _normalise_key(query: str) -> str:
    """Whitespace-collapse + lower-case ``query`` to a canonical cache key."""
    return " ".join(query.strip().lower().split())


class HuntCache:
    """In-memory LRU + TTL cache for translated NL hunt filters.

    ``max_entries=0`` disables the cache (every ``put`` is a no-op; every
    ``get`` is a miss). The TTL is checked lazily on access.
    """

    def __init__(self, *, max_entries: int = 256, ttl_seconds: int = 3600) -> None:
        if max_entries < 0:
            raise ValueError(f"max_entries must be >= 0, got {max_entries}")
        if ttl_seconds < 1:
            raise ValueError(f"ttl_seconds must be >= 1, got {ttl_seconds}")
        self._max_entries = int(max_entries)
        self._ttl_seconds = int(ttl_seconds)
        self._store: OrderedDict[str, tuple[dict[str, object], float]] = OrderedDict()
        self._lock = asyncio.Lock()
        # S-082: cumulative LRU+TTL evictions since process start.
        self._eviction_count = 0

    def __len__(self) -> int:
        return len(self._store)

    async def get(self, query: str) -> dict[str, object] | None:
        """Return a defensive copy of the cached filters, or ``None``."""
        key = _normalise_key(query)
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            filters, inserted_at = entry
            now = time.monotonic()
            if now - inserted_at > self._ttl_seconds:
                del self._store[key]
                self._eviction_count += 1
                return None
            self._store.move_to_end(key)
            # Defensive deep copy so the caller cannot mutate stored state.
            return copy.deepcopy(filters)

    async def put(self, query: str, filters: dict[str, object]) -> None:
        """Store a defensive copy of ``filters`` under the normalised key.

        When ``max_entries == 0`` the call is a no-op so the cache layer can
        be configured off without changing service-level code paths.
        """
        if self._max_entries == 0:
            return
        key = _normalise_key(query)
        snapshot = copy.deepcopy(filters)
        async with self._lock:
            now = time.monotonic()
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (snapshot, now)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)
                self._eviction_count += 1

    async def clear(self) -> None:
        """Remove all entries."""
        async with self._lock:
            self._store.clear()

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot."""
        return {
            "current": len(self._store),
            "max": self._max_entries,
            "evictions": self._eviction_count,
        }
