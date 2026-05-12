"""``ExplanationResult`` dataclass (S-071).

Immutable record returned by ``AlertExplanationService.explain(...)`` and
serialised by ``AlertExplanationResponse.from_result(...)``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExplanationResult:
    """Four-section alert explanation plus metadata.

    Attributes:
        alert_id: Alert identifier (UUID5 string).
        summary: 1-2 sentence headline.
        anomaly_rationale: Why this fires.
        contributing_events: Bullet lines pulled from events.
        recommended_next_steps: Bullet lines.
        model: Backend ``name`` that produced it (e.g. ``"llama_cpp"``).
        generated_at_ns: Epoch nanoseconds when the result was created.
        latency_ms: Wall time for the generation (0.0 on cache hit).
        cached: ``True`` on cache hit, ``False`` for a fresh generation.
        truncated: ``True`` when the prompt builder dropped contributing
            events to fit the character budget OR when ``LogStore`` returned
            fewer contributing events than ``alert.contributing_events``
            referenced (stale event IDs).
    """

    alert_id: str
    summary: str
    anomaly_rationale: str
    contributing_events: tuple[str, ...]
    recommended_next_steps: tuple[str, ...]
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool
    truncated: bool
