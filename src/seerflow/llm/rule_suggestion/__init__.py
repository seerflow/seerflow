"""Sigma rule suggestion from TP feedback (S-100, FR-066).

When a recurring ML-detected pattern accumulates three or more TP-marks,
``RuleSuggestionService`` asks the configured ``LLMBackend`` to draft a
Sigma YAML rule that would have caught the same pattern deterministically.
The drafted rule is **never** auto-applied — it lands in a cache the
dashboard can surface for human review (Monaco editor) and optional
promotion through the existing ``POST /api/v1/sigma/rules`` upload route.

Public re-exports keep the package surface small. The aggregator,
prompt builder, and parser are pure helpers that consumers should import
from their submodules directly when needed.
"""

from __future__ import annotations

from seerflow.llm.rule_suggestion.aggregator import PatternFeedbackRow, count_pattern_tps
from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
from seerflow.llm.rule_suggestion.pattern_keys import derive_pattern_key
from seerflow.llm.rule_suggestion.result import RuleSuggestionResult, ValidationStage
from seerflow.llm.rule_suggestion.service import RuleSuggestionService

__all__ = [
    "PatternFeedbackRow",
    "RuleSuggestionCache",
    "RuleSuggestionResult",
    "RuleSuggestionService",
    "ValidationStage",
    "count_pattern_tps",
    "derive_pattern_key",
]
