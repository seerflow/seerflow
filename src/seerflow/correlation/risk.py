"""Per-entity risk accumulation with exponential decay."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskEntry:
    """A single risk contribution to an entity's register."""

    timestamp_ns: int
    risk_points: float
    source: str  # "ml" | "sigma" | "correlation"
    rule_name: str
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()


class RiskRegister:
    """Per-entity risk accumulator with exponential decay.

    Each entity maintains a list of RiskEntry objects. The cumulative
    risk score is computed as::

        sum(entry.risk_points * exp(-lambda * (now - entry.timestamp_ns)))

    where ``lambda = ln(2) / half_life_ns``.
    """

    __slots__ = ("_entries", "_half_life_ns", "_lambda", "_max_entities", "_threshold")

    def __init__(
        self,
        half_life_ns: int,
        threshold: float,
        max_entities: int = 10_000,
    ) -> None:
        self._half_life_ns = half_life_ns
        self._lambda = math.log(2) / half_life_ns
        self._threshold = threshold
        self._max_entities = max_entities
        self._entries: dict[str, list[RiskEntry]] = {}

    def add_risk(self, entity_id: str, entry: RiskEntry) -> float:
        """Add a risk entry and return the current accumulated score."""
        if entity_id in self._entries:
            # Move to end for LRU tracking
            self._entries[entity_id] = self._entries.pop(entity_id)
        else:
            while len(self._entries) >= self._max_entities:
                oldest = next(iter(self._entries))
                del self._entries[oldest]
            self._entries[entity_id] = []
        self._entries[entity_id].append(entry)
        return self.get_risk(entity_id)

    def get_risk(self, entity_id: str) -> float:
        """Get current risk score with exponential decay applied."""
        entries = self._entries.get(entity_id)
        if not entries:
            return 0.0
        now = time.time_ns()
        total = 0.0
        for entry in entries:
            age_ns = now - entry.timestamp_ns
            if age_ns < 0:
                age_ns = 0
            total += entry.risk_points * math.exp(-self._lambda * age_ns)
        return total

    def check_threshold(self, entity_id: str) -> bool:
        """Check if entity's accumulated risk exceeds the threshold."""
        return self.get_risk(entity_id) >= self._threshold

    def get_entries(self, entity_id: str) -> list[RiskEntry]:
        """Get raw risk entries for an entity (for inspection/debugging)."""
        return list(self._entries.get(entity_id, []))

    @property
    def entity_count(self) -> int:
        """Number of entities currently tracked."""
        return len(self._entries)
