"""``HuntResult`` dataclass (S-072).

Immutable record returned by ``NaturalLanguageHuntService.hunt(...)``.
Storage-agnostic: events are passed through as ``SeerflowEvent`` instances;
the API and CLI layers convert them to their respective response shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class HuntResult:
    """Natural language hunt result with provenance and metadata.

    Attributes:
        query: Original NL query (verbatim, pre-normalisation).
        filters: Translated filter payload echoed back so the caller can
            see what the LLM understood.
        events: Resulting events, newest-first (matches ``LogStore``
            contract).
        total: Total matching events (may exceed ``len(events)`` when
            truncated by ``hunt_max_results``).
        model: Backend ``name`` that produced the translation
            (e.g. ``"llama_cpp"``).
        generated_at_ns: Epoch nanoseconds when the result was created.
        latency_ms: Wall-clock time for the translation + storage query
            (0.0 on cache hit, where only the storage query ran).
        cached: ``True`` when the translation came from the cache.
        truncated: ``True`` when the result page was capped at
            ``hunt_max_results``.
    """

    query: str
    filters: dict[str, object]
    events: tuple[SeerflowEvent, ...]
    total: int
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool
    truncated: bool
