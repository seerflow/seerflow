"""Custom Sigma detection matcher for SeerflowEvent fields.

Walks pySigma's parsed detection tree and evaluates conditions against event
field dicts.  This replaces a full pySigma Backend (which requires 30+ abstract
methods for query-string generation) with focused in-memory matching.

Tree structure after ``SigmaCondition.parsed``:
  - Leaf: ``ConditionFieldEqualsValueExpression``  (.field, .value)
  - Branch: ``ConditionAND`` / ``ConditionOR`` / ``ConditionNOT``  (.args)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sigma.conditions import (
    ConditionAND,
    ConditionFieldEqualsValueExpression,
    ConditionNOT,
    ConditionOR,
    ConditionValueExpression,
)
from sigma.types import SigmaString, SpecialChars

from seerflow.models.event import SeverityLevel
from seerflow.sigma.attack import is_valid_tactic
from seerflow.sigma.ids import compute_rule_id
from seerflow.sigma.pipeline import TUPLE_FIELDS

if TYPE_CHECKING:
    from sigma.rule import SigmaRule

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompiledRule:
    """A Sigma rule compiled for in-memory evaluation."""

    rule_id: str
    rule_name: str
    description: str
    severity: SeverityLevel
    attack_tactics: tuple[str, ...]
    attack_techniques: tuple[str, ...]
    logsource_key: tuple[str, str, str]
    _rule: SigmaRule  # keep reference for condition evaluation


_SIGMA_LEVEL_MAP: dict[str | None, SeverityLevel] = {
    "informational": SeverityLevel.INFORMATIONAL,
    "low": SeverityLevel.NOTICE,
    "medium": SeverityLevel.WARNING,
    "high": SeverityLevel.ERROR,
    "critical": SeverityLevel.CRITICAL,
    None: SeverityLevel.INFORMATIONAL,
}


_regex_cache: dict[str, re.Pattern[str]] = {}


def _sigma_string_to_regex(s: SigmaString) -> re.Pattern[str]:
    """Convert a pySigma SigmaString (with wildcards) to a compiled regex.

    ``SigmaString.s`` is a list of ``str | SpecialChars`` parts.
    ``WILDCARD_MULTI`` -> ``.*``, ``WILDCARD_SINGLE`` -> ``.``.
    The regex is anchored (``^...$``) and case-insensitive.
    Adjacent ``WILDCARD_MULTI`` tokens are collapsed to prevent ReDoS.
    Results are cached by pattern string (not by object id, which can
    alias after garbage collection).
    """
    parts: list[str] = []
    prev_was_wildcard_multi = False
    for piece in s.s:
        if isinstance(piece, str):
            parts.append(re.escape(piece))
            prev_was_wildcard_multi = False
        elif piece == SpecialChars.WILDCARD_MULTI:
            if not prev_was_wildcard_multi:
                parts.append(".*")
                prev_was_wildcard_multi = True
        elif piece == SpecialChars.WILDCARD_SINGLE:
            parts.append(".")
            prev_was_wildcard_multi = False
    pattern = "^" + "".join(parts) + "$"
    cached = _regex_cache.get(pattern)
    if cached is not None:
        return cached
    result = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    _regex_cache[pattern] = result
    return result


def _extract_attack_tags(
    rule: SigmaRule,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract ATT&CK tactics and techniques from Sigma rule tags."""
    tactics: list[str] = []
    techniques: list[str] = []
    for tag in rule.tags:
        if tag.namespace != "attack":
            continue
        name = tag.name
        # Techniques start with "t" followed by digits (e.g. t1033, t1021.001)
        if name.startswith("t") and len(name) > 1 and name[1:2].isdigit():
            techniques.append(name)
        elif name.startswith("s") and len(name) > 1 and name[1:2].isdigit():
            # MITRE Software ID (e.g. attack.s0508 = Ngrok). SigmaHQ tags the
            # tool a rule detects; it is neither a tactic nor a technique, so
            # skip it silently rather than warn as an unknown tactic.
            continue
        else:
            # SigmaHQ tags multi-word tactics with hyphens
            # (``command-and-control``); our canonical map keys them with
            # underscores. Normalize so valid tactics resolve (and don't
            # trip the warning) and are stored in canonical form.
            tactic = name.replace("-", "_")
            if not is_valid_tactic(tactic):
                logger.warning(
                    "Unknown ATT&CK tactic '%s' in rule '%s'",
                    name,
                    rule.title or "Untitled",
                )
            tactics.append(tactic)
    return tuple(tactics), tuple(techniques)


def compile_rule(rule: SigmaRule) -> CompiledRule:
    """Compile a parsed SigmaRule into a CompiledRule for evaluation.

    The rule should already have had the seerflow pipeline applied
    (field names remapped to SeerflowEvent attributes).
    """
    ls = rule.logsource
    logsource_key = (
        ls.category or "",
        ls.product or "",
        ls.service or "",
    )
    tactics, techniques = _extract_attack_tags(rule)
    level_str = rule.level.name.lower() if rule.level else None
    severity = _SIGMA_LEVEL_MAP.get(level_str, SeverityLevel.INFORMATIONAL)

    return CompiledRule(
        rule_id=compute_rule_id(rule),
        rule_name=rule.title or "Untitled",
        description=rule.description or "",
        severity=severity,
        attack_tactics=tactics,
        attack_techniques=techniques,
        logsource_key=logsource_key,
        _rule=rule,
    )


def _match_field_value(
    field: str,
    sigma_value: SigmaString,
    event: dict[str, Any],
) -> bool:
    """Match a single field/value pair against an event dict.

    For tuple fields (``related_ips``, etc.) checks if *any* element matches.
    For scalar fields, checks the value directly.
    """
    event_value = event.get(field)
    if event_value is None:
        return False

    pattern = _sigma_string_to_regex(sigma_value)
    is_tuple = field in TUPLE_FIELDS

    if is_tuple and isinstance(event_value, tuple):
        return any(pattern.search(str(v)) is not None for v in event_value)
    return pattern.search(str(event_value)) is not None


def _eval_node(node: Any, event: dict[str, Any]) -> bool:
    """Recursively evaluate a parsed Sigma condition tree node.

    Node types (from ``sigma.conditions``):
    - ``ConditionFieldEqualsValueExpression``: leaf — field == value
    - ``ConditionAND``: all children must match
    - ``ConditionOR``: any child must match
    - ``ConditionNOT``: single child must *not* match
    """
    if isinstance(node, ConditionFieldEqualsValueExpression):
        field: str = node.field or "message"
        value = node.value
        if isinstance(value, SigmaString):
            return _match_field_value(field, value, event)
        # Non-string value (int/float) — direct equality
        event_value = event.get(field)
        if event_value is None:
            return False
        if field in TUPLE_FIELDS and isinstance(event_value, tuple):
            return value in event_value
        return bool(event_value == value)

    if isinstance(node, ConditionValueExpression):
        # Keyword condition (no field) — substring search in message
        value = node.value
        message = str(event.get("message", ""))
        if isinstance(value, SigmaString):
            plain = str(value)
            return plain.lower() in message.lower()
        return str(value).lower() in message.lower()

    if isinstance(node, ConditionAND):
        return all(_eval_node(arg, event) for arg in node.args)

    if isinstance(node, ConditionOR):
        return any(_eval_node(arg, event) for arg in node.args)

    if isinstance(node, ConditionNOT):
        return not _eval_node(node.args[0], event)

    logger.warning("Unknown condition node type: %s", type(node).__name__)
    return False


def match_event(compiled: CompiledRule, event: dict[str, Any]) -> bool:
    """Evaluate a CompiledRule against an event field dict.

    Walks the rule's parsed condition tree, evaluating leaf nodes
    (``ConditionFieldEqualsValueExpression``) against the event.
    """
    rule = compiled._rule
    conditions = rule.detection.parsed_condition
    if not conditions:
        return False
    return all(_eval_node(c.parsed, event) for c in conditions)
