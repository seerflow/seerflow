"""Per-entity sliding window buffer for temporal correlation."""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import TimeRange


class EntityWindowBuffer:
    """Sliding window buffer that maintains recent events per entity.

    Each entity gets a ``deque(maxlen=max_events)`` for bounded memory.
    Events older than ``window_ns`` are lazily pruned on query.
    """

    __slots__ = (
        "_buffers",
        "_clock_ns",
        "_eviction_count",
        "_max_entities",
        "_max_events",
        "_window_ns",
    )

    def __init__(
        self,
        window_ns: int,
        max_events: int = 1000,
        max_entities: int = 10_000,
        *,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._window_ns = window_ns
        self._max_events = max_events
        self._max_entities = max_entities
        # S-334: the "now" used to compute the lazy-prune cutoff is
        # dependency-injected (defaults to wall-clock ``time.time_ns``).
        # The LANL determinism harness injects a frozen replay-epoch clock so
        # pruning is a pure function of the rebased event timestamps —
        # invariant to real wall-clock drift on a slow CI runner. Production
        # keeps the default, so live behaviour is byte-identical.
        self._clock_ns = clock_ns
        self._buffers: dict[str, deque[SeerflowEvent]] = {}
        # S-082: cumulative LRU evictions since process start. Exposed via
        # ``bounds()`` for the memory-bounds audit.
        self._eviction_count = 0

    def add_event(self, entity_uuid: str, event: SeerflowEvent) -> None:
        """Add an event to the entity's window buffer.

        Uses LRU eviction: entities are moved to the end of the dict
        on each access, so the least-recently-used entity is always first.
        """
        if entity_uuid in self._buffers:
            # Move to end (most recently used)
            self._buffers[entity_uuid] = self._buffers.pop(entity_uuid)
        else:
            # Evict LRU entity if at capacity
            while len(self._buffers) >= self._max_entities:
                oldest_key = next(iter(self._buffers))
                del self._buffers[oldest_key]
                self._eviction_count += 1
            self._buffers[entity_uuid] = deque(maxlen=self._max_events)
        self._buffers[entity_uuid].append(event)

    def query(
        self,
        entity_uuid: str,
        *,
        time_range: TimeRange | None = None,
        source_types: tuple[str, ...] | None = None,
    ) -> list[SeerflowEvent]:
        """Query events for an entity, with optional time range and source filter.

        Lazily prunes expired events before returning results.
        Returns events sorted by timestamp ascending.
        """
        buf = self._buffers.get(entity_uuid)
        if buf is None:
            return []

        # Lazy prune expired events from the left
        cutoff = self._clock_ns() - self._window_ns
        while buf and buf[0].timestamp_ns < cutoff:
            buf.popleft()

        if not buf:
            del self._buffers[entity_uuid]
            return []

        results = list(buf)

        if time_range is not None:
            results = [
                e for e in results if time_range.start_ns <= e.timestamp_ns <= time_range.end_ns
            ]

        if source_types is not None:
            results = [e for e in results if e.source_type in source_types]

        return sorted(results, key=lambda e: e.timestamp_ns)

    def prune(self) -> None:
        """Remove all expired events and empty entity buffers."""
        cutoff = self._clock_ns() - self._window_ns
        empty_keys: list[str] = []
        for entity_uuid, buf in self._buffers.items():
            while buf and buf[0].timestamp_ns < cutoff:
                buf.popleft()
            if not buf:
                empty_keys.append(entity_uuid)
        for key in empty_keys:
            del self._buffers[key]

    def stats(self) -> dict[str, int]:
        """Return buffer statistics."""
        total = sum(len(buf) for buf in self._buffers.values())
        return {
            "entity_count": len(self._buffers),
            "total_events": total,
        }

    @property
    def entity_count(self) -> int:
        """Number of entities currently tracked."""
        return len(self._buffers)

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot.

        ``current`` is the number of tracked entities (not the aggregate
        event count — capacity is bounded by ``max_entities``, not by the
        per-entity deque sum). ``max`` mirrors the configured cap.
        ``evictions`` is cumulative since process start.
        """
        return {
            "current": len(self._buffers),
            "max": self._max_entities,
            "evictions": self._eviction_count,
        }
