"""Correlation engine: evaluates rules against entity-temporal windows.

Matches incoming events against ``CorrelationRule`` definitions by
querying the ``EntityWindowBuffer`` for each entity reference.
Pre-compiles regex patterns at init for throughput.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from seerflow.models.alert import Alert
from seerflow.models.entity import infer_entity_type, primary_entity_value

if TYPE_CHECKING:
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.models.alert import CorrelationRule
    from seerflow.models.event import SeerflowEvent


class CorrelationEngine:
    """Evaluates correlation rules against entity-temporal windows."""

    __slots__ = ("_compiled", "_rules", "_window")

    def __init__(
        self,
        rules: list[CorrelationRule],
        window: EntityWindowBuffer,
    ) -> None:
        self._rules = rules
        self._window = window
        # Pre-compile regex patterns: rule_name -> source_idx -> {field: compiled_pattern}
        self._compiled: dict[str, list[dict[str, re.Pattern[str]]]] = {}
        for rule in rules:
            patterns: list[dict[str, re.Pattern[str]]] = []
            for src in rule.sources:
                compiled: dict[str, re.Pattern[str]] = {}
                for field, pattern in src.conditions.items():
                    compiled[field] = re.compile(pattern)
                patterns.append(compiled)
            self._compiled[rule.name] = patterns

    def evaluate(
        self,
        event: SeerflowEvent,
        entity_refs: tuple[str, ...],
    ) -> list[Alert]:
        """Evaluate all rules against the entity's window buffer.

        Returns a list of alerts for rules whose conditions are met
        for any of the provided entity references.
        """
        if not self._rules or not entity_refs:
            return []

        alerts: list[Alert] = []
        for entity_uuid in entity_refs:
            for rule in self._rules:
                alert = self._evaluate_rule(rule, entity_uuid, event)
                if alert is not None:
                    alerts.append(alert)
        return alerts

    def _evaluate_rule(
        self,
        rule: CorrelationRule,
        entity_uuid: str,
        trigger_event: SeerflowEvent,
    ) -> Alert | None:
        """Evaluate a single rule for a single entity. Returns alert or None."""
        # Check entity type matches
        event_entity_type = infer_entity_type(trigger_event)
        if event_entity_type != rule.entity_type:
            return None

        # Query events within the rule's temporal window
        from seerflow.models.query import TimeRange

        rule_window_ns = rule.window_seconds * 1_000_000_000
        cutoff_ns = trigger_event.timestamp_ns - rule_window_ns
        time_range = TimeRange(start_ns=cutoff_ns, end_ns=trigger_event.timestamp_ns)
        window_events = self._window.query(entity_uuid, time_range=time_range)
        if not window_events:
            return None

        # For each source condition, check if enough matching events exist
        matched_sources = 0
        contributing_event_ids: list[uuid.UUID] = []

        for source_idx, source in enumerate(rule.sources):
            # Filter window events by source_type
            source_events = [e for e in window_events if e.source_type == source.source_type]

            # Filter by regex conditions
            matching = [
                e
                for e in source_events
                if self._match_event(e, source_idx=source_idx, rule_name=rule.name)
            ]

            if len(matching) >= source.min_count:
                matched_sources += 1
                contributing_event_ids.extend(e.event_id for e in matching)

        if matched_sources < rule.min_sources:
            return None

        return self._create_alert(
            rule=rule,
            entity_uuid=entity_uuid,
            trigger_event=trigger_event,
            contributing_event_ids=tuple(contributing_event_ids),
        )

    def _match_event(
        self,
        event: SeerflowEvent,
        source_idx: int,
        rule_name: str,
    ) -> bool:
        """Check if an event matches all compiled conditions for a source."""
        patterns = self._compiled[rule_name][source_idx]
        for field, pattern in patterns.items():
            value = getattr(event, field, None)
            if value is None:
                return False
            # Handle tuple fields (related_ips, related_users, etc.)
            if isinstance(value, tuple):
                if not any(pattern.search(str(v)) for v in value):
                    return False
            else:
                if not pattern.search(str(value)):
                    return False
        return True

    @staticmethod
    def _create_alert(
        *,
        rule: CorrelationRule,
        entity_uuid: str,
        trigger_event: SeerflowEvent,
        contributing_event_ids: tuple[uuid.UUID, ...],
    ) -> Alert:
        """Build an Alert from a fired correlation rule."""
        # Risk score: blend rule severity with number of contributing events
        # severity_weight = rule.alert_severity.value / 6  (normalize to [0, 1])
        # event_weight = min(len(contributing_event_ids) / 10, 1.0)  (cap at 10)
        # risk_score = severity_weight * 0.6 + event_weight * 0.4
        n_events = len(contributing_event_ids)
        if n_events == 0:
            risk_score = 0.0
        else:
            severity_weight = rule.alert_severity.value / 6
            event_weight = min(n_events / 10, 1.0)
            risk_score = severity_weight * 0.6 + event_weight * 0.4

        return Alert(
            alert_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"corr:{rule.name}:{entity_uuid}:{trigger_event.timestamp_ns}",
                )
            ),
            alert_type="correlation",
            timestamp_ns=trigger_event.timestamp_ns,
            severity_id=rule.alert_severity,
            rule_name=rule.name,
            description=(f"Correlation rule '{rule.name}' fired: {rule.description}"),
            entity_uuid=entity_uuid,
            entity_value=primary_entity_value(trigger_event),
            entity_type=infer_entity_type(trigger_event),
            contributing_events=contributing_event_ids,
            mitre_tactics=rule.mitre_tactics,
            mitre_techniques=rule.mitre_techniques,
            risk_score=risk_score,
            dedup_key=f"corr:{rule.name}:{entity_uuid}",
        )
