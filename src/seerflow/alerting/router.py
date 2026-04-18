"""Notification routing rules (S-164).

Rules sit between the AlertDispatcher and configured DeliveryTargets. They
match alerts on ``alert_type``, ``rule_name`` (glob), ``entity_type`` and
severity bounds, then dispatch either immediately or via a digest buffer.

Quiet hours apply per-channel and may suppress non-critical alerts inside a
configured HH:MM UTC window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import time

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
