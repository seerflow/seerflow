"""``RuleSuggestionResult`` dataclass (S-100).

Immutable record returned by ``RuleSuggestionService.suggest(...)``. Carries
the drafted Sigma YAML, the structured validation verdict (so the dashboard
can show a "fix the YAML" hint), and the metadata that lets the UI display
provenance (model, latency, cache hit/miss).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The validator returns one of three failure stages on a bad rule; ``"ok"``
# means the YAML parses + matches the SigmaHQ schema + compiles through the
# seerflow pipeline. Centralised here so the API schema can re-import the
# same Literal for response validation.
ValidationStage = Literal["ok", "yaml", "schema", "compile"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleSuggestionResult:
    """Outcome of one LLM-drafted Sigma rule suggestion.

    Attributes:
        pattern_key: ``"{alert_type}:{rule_name}:{entity_type}"``.
        tp_count: TP count at suggestion time (snapshot, not live).
        yaml: The drafted YAML body. May be empty when the LLM returned
            nothing parseable; ``validation_stage`` reflects the verdict
            either way.
        title: ``title`` field parsed from the YAML; empty string when the
            validator could not extract one.
        logsource_key: ``(category, product, service)`` triple drawn from
            the YAML ``logsource`` block. Empty tuple on validation
            failure.
        validation_stage: ``"ok"`` when the validator accepted the YAML;
            otherwise the first failing stage (``"yaml"`` for syntax,
            ``"schema"`` for SigmaHQ schema violation, ``"compile"`` for a
            seerflow pipeline error).
        validation_message: Human-readable message from the validator.
            Empty string when ``validation_stage == "ok"``.
        contributing_alert_ids: TP-confirmed alert IDs that drove the
            prompt (newest first, cap 16).
        model: Backend ``name`` that produced the draft (e.g.
            ``"llama_cpp"``, ``"ollama"``, ``"anthropic"``).
        generated_at_ns: Epoch nanoseconds when the result was minted.
        latency_ms: Wall-time for the generation. ``0.0`` on cache hit.
        cached: ``True`` on cache hit, ``False`` on a fresh generation.
    """

    pattern_key: str
    tp_count: int
    yaml: str
    title: str
    logsource_key: tuple[str, ...]
    validation_stage: ValidationStage
    validation_message: str
    contributing_alert_ids: tuple[str, ...]
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool
