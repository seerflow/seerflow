"""Persistence Protocol for per-rule Sigma state (enabled flag + counters)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class SigmaRuleState:
    """Persistent state for a single Sigma rule."""

    rule_id: str
    enabled: bool
    match_count_lifetime: int
    last_fired_ns: int | None
    updated_at_ns: int


@runtime_checkable
class SigmaRuleStateStore(Protocol):  # pragma: no cover
    """KV-style persistence for Sigma rule enabled flags and match counters."""

    async def get_all(self) -> dict[str, SigmaRuleState]:
        """Return every persisted rule state, keyed by ``rule_id``."""
        ...

    async def set_enabled(self, rule_id: str, enabled: bool) -> None:
        """Upsert the enabled flag for *rule_id* and bump ``updated_at_ns``."""
        ...

    async def increment_counts(self, deltas: Mapping[str, tuple[int, int]]) -> None:
        """Bulk-increment counters.

        *deltas* maps ``rule_id`` -> ``(count_delta, last_fired_ns)``. Implementations
        upsert rows and update ``last_fired_ns`` to ``max(existing, last_fired_ns)``.
        """
        ...
