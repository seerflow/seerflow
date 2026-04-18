"""Notification routing rules (S-164).

Rules sit between the AlertDispatcher and configured DeliveryTargets. They
match alerts on ``alert_type``, ``rule_name`` (glob), ``entity_type`` and
severity bounds, then dispatch either immediately or via a digest buffer.

Quiet hours apply per-channel and may suppress non-critical alerts inside a
configured HH:MM UTC window.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import time

    from seerflow.alerting.target import DeliveryTarget
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

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


def _default_utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationRouter:
    """Evaluates routing rules and dispatches alerts to named targets.

    Thread-safety: the router is single-coroutine; it must only be driven
    from the AlertDispatcher worker loop.
    """

    def __init__(
        self,
        *,
        targets: Iterable[DeliveryTarget],
        rules: Sequence[RoutingRule] = (),
        default_routing: DefaultRouting | None = None,
        now_fn: Callable[[], datetime] = _default_utc_now,
    ) -> None:
        self._targets: dict[str, DeliveryTarget] = {}
        for t in targets:
            if t.name in self._targets:
                msg = f"duplicate DeliveryTarget name: {t.name!r}"
                raise ValueError(msg)
            self._targets[t.name] = t
        self._rules: tuple[RoutingRule, ...] = tuple(rules)
        self._default = default_routing or DefaultRouting(action="drop")
        self._now = now_fn
        self._running = True

    async def start(self) -> None:
        """Reserved for Task 8's digest flushers. No-op today."""
        self._running = True

    async def stop(self) -> None:
        """Reserved for Task 8's digest flush-on-stop. No-op today."""
        self._running = False

    async def route(self, alert: Alert) -> None:
        """Find the first matching rule (or default) and dispatch."""
        notify = self._select_notify(alert)
        for entry in notify:
            target = self._targets.get(entry.channel)
            if target is None:
                _log.error(
                    "NotificationRouter: rule references unknown channel %r, dropping",
                    entry.channel,
                )
                continue
            if int(alert.severity_id) < target.min_severity:
                continue
            # Digest handling lands in Task 8; for now every entry is treated
            # as immediate.
            await self._safe_deliver(target, alert)

    def _select_notify(self, alert: Alert) -> tuple[RoutingRuleNotify, ...]:
        for rule in self._rules:
            if _rule_matches(rule, alert):
                return rule.notify
        if self._default.action == "notify":
            return self._default.notify
        return ()

    async def _safe_deliver(self, target: DeliveryTarget, alert: Alert) -> None:
        try:
            await target.deliver(alert)
        except Exception:
            _log.exception(
                "NotificationRouter: delivery failed for channel %r alert %s",
                target.name,
                alert.alert_id,
            )
