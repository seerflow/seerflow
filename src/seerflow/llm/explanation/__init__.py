"""Alert explanation generation (S-071).

Public surface:

- ``ExplanationResult`` — immutable 4-section explanation record.
- ``ExplanationCache`` — bounded LRU + TTL cache keyed by ``alert_id``.
- ``AlertExplanationService`` — orchestrates load → prompt → call → cache.
"""

from __future__ import annotations

from seerflow.llm.explanation.cache import ExplanationCache
from seerflow.llm.explanation.result import ExplanationResult
from seerflow.llm.explanation.service import AlertExplanationService

__all__ = [
    "AlertExplanationService",
    "ExplanationCache",
    "ExplanationResult",
]
