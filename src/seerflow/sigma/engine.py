"""SigmaEngine -- load, index, and evaluate Sigma rules against SeerflowEvents.

Orchestrates:
1. YAML loading via ``SigmaRule.from_yaml()``
2. Field remapping via ``seerflow_pipeline()``
3. Compilation via ``compile_rule()``
4. Logsource-indexed dispatch for fast per-event evaluation
5. Alert creation for matching rules
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sigma.rule import SigmaRule

from seerflow.models.alert import Alert
from seerflow.models.entity import infer_entity_type
from seerflow.sigma.bundled import get_bundled_rule_paths
from seerflow.sigma.matcher import CompiledRule, compile_rule, match_event
from seerflow.sigma.pipeline import seerflow_pipeline

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from seerflow.models.event import SeerflowEvent

logger = logging.getLogger(__name__)

# Stable namespace for deterministic alert IDs (uuid5).
# DO NOT CHANGE in production — changing this invalidates all existing
# alert IDs and breaks deduplication across restarts.
_NAMESPACE_SIGMA = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _event_to_dict(event: SeerflowEvent) -> dict[str, object]:
    """Convert a SeerflowEvent to a flat dict for matcher evaluation."""
    return {
        "message": event.message,
        "source_type": event.source_type,
        "template_id": event.template_id,
        "template_str": event.template_str,
        "related_ips": event.related_ips,
        "related_users": event.related_users,
        "related_hosts": event.related_hosts,
        "related_hashes": event.related_hashes,
        "severity_id": event.severity_id.value,
        "event_category": event.event_category,
        "event_type": event.event_type,
        "event_action": event.event_action,
    }


class SigmaEngine:
    """Sigma rule evaluation engine with logsource-indexed dispatch.

    Usage::

        engine = SigmaEngine()
        engine.load_rules([Path("rules/whoami.yml")])
        alerts = engine.evaluate(event)
    """

    def __init__(self) -> None:
        self._index: dict[tuple[str, str, str], list[CompiledRule]] = {}
        self._rule_count: int = 0
        self._pipeline = seerflow_pipeline()

    def load_rules(self, paths: Sequence[Path]) -> None:
        """Load, compile, and index Sigma rules from YAML file paths.

        Invalid rules are logged as warnings and skipped.

        Security: callers must ensure paths are within a trusted directory.
        This method does not enforce path boundaries — it reads whatever
        paths are given. Use S-030's validated rule loading for user-supplied
        rule directories.
        """
        for path in paths:
            try:
                rule = SigmaRule.from_yaml(path.read_text())
                self._pipeline.apply(rule)
                compiled = compile_rule(rule)
                self._index.setdefault(compiled.logsource_key, []).append(compiled)
                self._rule_count += 1
            except Exception:
                logger.warning("Failed to load Sigma rule: %s", path, exc_info=True)

        logger.info(
            "Sigma engine loaded %d rules across %d logsource groups",
            self._rule_count,
            len(self._index),
        )

    def load_bundled(self) -> None:
        """Load all bundled SigmaHQ rules from the package.

        Convenience method for zero-config startup. Equivalent to::

            engine.load_rules(get_bundled_rule_paths())
        """
        self.load_rules(get_bundled_rule_paths())

    def load_custom(self, dirs: Sequence[str]) -> None:
        """Load custom Sigma rules from operator-specified directories.

        Validates directories, discovers ``.yml`` files, and loads them
        via ``load_rules()``. Invalid directories and rules are logged
        as warnings and skipped.
        """
        from seerflow.sigma.loader import discover_custom_rules

        self.load_rules(discover_custom_rules(dirs))

    def evaluate(self, event: SeerflowEvent) -> list[Alert]:
        """Evaluate event against applicable rules using logsource dispatch.

        Performs hierarchical logsource lookup (4 keys from most specific
        to least specific) and returns an Alert for each matching rule.
        """
        cat = event.log_source_category
        prod = event.log_source_product
        svc = event.log_source_service

        # Hierarchical lookup: most specific -> least specific.
        # Use dict.fromkeys to deduplicate keys while preserving order.
        candidates: list[CompiledRule] = []
        seen: set[int] = set()
        for key in dict.fromkeys(
            (
                (cat, prod, svc),
                (cat, prod, ""),
                (cat, "", ""),
                ("", "", ""),
            )
        ):
            for rule in self._index.get(key, ()):
                rule_id = id(rule)
                if rule_id not in seen:
                    seen.add(rule_id)
                    candidates.append(rule)

        if not candidates:
            return []

        event_dict = _event_to_dict(event)
        alerts: list[Alert] = []

        for compiled in candidates:
            try:
                if match_event(compiled, event_dict):
                    alerts.append(_create_sigma_alert(compiled, event))
            except Exception:
                logger.warning(
                    "Error evaluating rule '%s' against event %s",
                    compiled.rule_name,
                    event.event_id,
                    exc_info=True,
                )

        return alerts

    @property
    def rule_count(self) -> int:
        """Total number of loaded rules."""
        return self._rule_count

    @property
    def logsource_summary(self) -> dict[tuple[str, str, str], int]:
        """Map of logsource key -> number of rules."""
        return {k: len(v) for k, v in self._index.items()}


def _create_sigma_alert(compiled: CompiledRule, event: SeerflowEvent) -> Alert:
    """Create an Alert from a matching Sigma rule and triggering event."""
    entity_refs = event.entity_refs
    raw_value = (
        event.related_ips[0]
        if event.related_ips
        else event.related_users[0]
        if event.related_users
        else event.related_hosts[0]
        if event.related_hosts
        else ""
    )
    alert_id = str(
        uuid.uuid5(
            _NAMESPACE_SIGMA,
            f"{compiled.rule_name}:{event.event_id}",
        )
    )
    return Alert(
        alert_id=alert_id,
        alert_type="sigma",
        timestamp_ns=event.timestamp_ns,
        severity_id=compiled.severity,
        rule_name=compiled.rule_name,
        description=compiled.description,
        entity_uuid=entity_refs[0] if entity_refs else "",
        entity_value=raw_value,
        entity_type=infer_entity_type(event),
        contributing_events=(event.event_id,),
        mitre_tactics=compiled.attack_tactics,
        mitre_techniques=compiled.attack_techniques,
        dedup_key=(
            f"sigma:{compiled.rule_name}:{event.source_type}"
            f":{entity_refs[0] if entity_refs else ''}"
        ),
    )
