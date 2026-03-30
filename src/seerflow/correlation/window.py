"""Per-entity sliding window buffer for temporal correlation."""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import TimeRange


class EntityWindowBuffer:
    """Sliding window buffer that maintains recent events per entity.

    Each entity gets a ``deque(maxlen=max_events)`` for bounded memory.
    Events older than ``window_ns`` are lazily pruned on query.
    """

    __slots__ = ("_buffers", "_max_events", "_window_ns")

    def __init__(self, window_ns: int, max_events: int = 1000) -> None:
        self._window_ns = window_ns
        self._max_events = max_events
        self._buffers: dict[str, deque[SeerflowEvent]] = {}

    def add_event(self, entity_uuid: str, event: SeerflowEvent) -> None:
        """Add an event to the entity's window buffer."""
        if entity_uuid not in self._buffers:
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
        cutoff = time.time_ns() - self._window_ns
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
        cutoff = time.time_ns() - self._window_ns
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
