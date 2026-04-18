"""Notification routing rules (S-164).

Rules sit between the AlertDispatcher and configured DeliveryTargets. They
match alerts on ``alert_type``, ``rule_name`` (glob), ``entity_type`` and
severity bounds, then dispatch either immediately or via a digest buffer.

Quiet hours apply per-channel and may suppress non-critical alerts inside a
configured HH:MM UTC window.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import time

    from seerflow.models.alert import Alert

Mode = Literal["immediate", "digest"]
DefaultAction = Literal["drop", "notify"]


@dataclass(frozen=True, kw_only=True, slots=True)
class QuietHours:
    """Per-channel suppression window in UTC.

    ``start`` is inclusive, ``end`` is exclusive. When ``start > end`` the
    window wraps midnight. Alerts with ``severity_id < min_severity`` while
    inside the window are dropped (logged at INFO).
    """

    start: time
    end: time
    min_severity: int


@dataclass(frozen=True, kw_only=True, slots=True)
class RoutingRuleMatch:
    """Predicates for first-match-wins rule evaluation (AND across fields)."""

    alert_type: str | tuple[str, ...] | None = None
    rule_name: str | None = None  # fnmatch.fnmatchcase glob
    entity_type: str | tuple[str, ...] | None = None
    min_severity: int | None = None
    max_severity: int | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class RoutingRuleNotify:
    """Per-channel dispatch config inside a rule."""

    channel: str
    mode: Mode = "immediate"
    digest_window_minutes: int = 15  # ignored when mode == "immediate"


@dataclass(frozen=True, kw_only=True, slots=True)
class RoutingRule:
    """One entry in ``alerting.routing_rules`` — evaluated top-down."""

    match: RoutingRuleMatch = field(default_factory=RoutingRuleMatch)
    notify: tuple[RoutingRuleNotify, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class DefaultRouting:
    """Behaviour for alerts that no rule matched."""

    action: DefaultAction = "drop"
    notify: tuple[RoutingRuleNotify, ...] = ()


def _matches_str_or_tuple(
    predicate: str | tuple[str, ...] | None, value: str
) -> bool:
    if predicate is None:
        return True
    if isinstance(predicate, str):
        return predicate == value
    return value in predicate


def _rule_matches(rule: RoutingRule, alert: Alert) -> bool:
    """Return True iff every non-None predicate on ``rule.match`` matches.

    Severity comparisons use the integer value of ``SeverityLevel``.
    ``rule_name`` is matched with ``fnmatch.fnmatchcase`` (case-sensitive glob).
    """
    m = rule.match
    if not _matches_str_or_tuple(m.alert_type, alert.alert_type):
        return False
    if m.rule_name is not None and not fnmatch.fnmatchcase(alert.rule_name, m.rule_name):
        return False
    if not _matches_str_or_tuple(m.entity_type, alert.entity_type):
        return False
    sev = int(alert.severity_id)
    if m.min_severity is not None and sev < m.min_severity:
        return False
    return not (m.max_severity is not None and sev > m.max_severity)
