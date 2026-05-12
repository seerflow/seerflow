"""Natural language threat hunting subpackage (S-072).

Public re-exports — concrete implementations live in sibling modules:

- ``HuntCache`` — LRU + TTL cache keyed by normalised NL query
- ``HuntResult`` — immutable result dataclass
- ``NaturalLanguageHuntService`` — orchestrator
- ``build_prompt`` / ``parse_response`` — pure translator helpers
- ``translate_to_event_query`` — pure filter validator
"""

from __future__ import annotations

from seerflow.llm.hunt._to_event_query import translate_to_event_query
from seerflow.llm.hunt.cache import HuntCache
from seerflow.llm.hunt.parser import parse_response
from seerflow.llm.hunt.prompt import build_prompt
from seerflow.llm.hunt.result import HuntResult
from seerflow.llm.hunt.service import NaturalLanguageHuntService

__all__ = [
    "HuntCache",
    "HuntResult",
    "NaturalLanguageHuntService",
    "build_prompt",
    "parse_response",
    "translate_to_event_query",
]
