"""SigmaEngine -- load, index, and evaluate Sigma rules against SeerflowEvents.

Orchestrates:
1. YAML loading via ``SigmaRule.from_yaml()``
2. Field remapping via ``seerflow_pipeline()``
3. Compilation via ``compile_rule()``
4. Logsource-indexed dispatch for fast per-event evaluation
5. Alert creation for matching rules
"""

from __future__ import annotations

import enum
import logging
import threading
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec.structs
from sigma.rule import SigmaRule

from seerflow.models.alert import Alert
from seerflow.models.entity import infer_entity_type, primary_entity_value
from seerflow.sigma.bundled import get_bundled_rule_paths
from seerflow.sigma.ids import compute_rule_id
from seerflow.sigma.matcher import CompiledRule, compile_rule, match_event
from seerflow.sigma.pipeline import seerflow_pipeline
from seerflow.sigma.validator import SigmaRuleValidationError, validate_yaml

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from seerflow.models.event import SeerflowEvent
    from seerflow.sigma.state import SigmaRuleStateStore

logger = logging.getLogger(__name__)

# Stable namespace for deterministic alert IDs (uuid5).
# DO NOT CHANGE in production — changing this invalidates all existing
# alert IDs and breaks deduplication across restarts.
_NAMESPACE_SIGMA = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


# Fields to exclude from Sigma rule matching (large/binary or not useful).
_EXCLUDED_FIELDS = frozenset({"body", "raw_event"})


def _event_to_dict(event: SeerflowEvent) -> dict[str, object]:
    """Convert a SeerflowEvent to a flat dict for matcher evaluation.

    Uses msgspec struct introspection to include all fields dynamically,
    so new SeerflowEvent fields are automatically available to Sigma rules.
    """
    d: dict[str, object] = {}
    for field in msgspec.structs.fields(event):
        if field.name in _EXCLUDED_FIELDS:
            continue
        val = getattr(event, field.name)
        # Convert enums to their value for string-based Sigma matching
        if isinstance(val, enum.Enum):
            val = val.value
        d[field.name] = val
    return d


@dataclass(frozen=True)
class SigmaRuleCollisionError(Exception):
    """Raised when ``add_rule`` produces a ``rule_id`` already loaded."""

    rule_id: str
    existing_source: str

    def __str__(self) -> str:
        return f"rule_id {self.rule_id} already loaded (source={self.existing_source})"


class SigmaEngine:
    """Sigma rule evaluation engine with logsource-indexed dispatch.

    Usage::

        engine = SigmaEngine()
        engine.load_rules([Path("rules/whoami.yml")])
        alerts = engine.evaluate(event)

    Mutation safety
    ---------------
    ``set_enabled`` and ``add_rule`` mutate via copy-on-write under a
    ``threading.Lock``. The hot ``evaluate`` path is sync and reads through
    a single attribute access, so readers always see a coherent snapshot.
    """

    def __init__(self) -> None:
        self._index: dict[tuple[str, str, str], list[CompiledRule]] = {}
        self._rule_count: int = 0
        self._pipeline = seerflow_pipeline()
        self._disabled_rule_ids: frozenset[str] = frozenset()
        self._mutation_lock = threading.Lock()
        self._match_counts: Counter[str] = Counter()
        self._last_fired_ns: dict[str, int] = {}
        self._yaml_source: dict[str, str] = {}
        self._source_kind: dict[str, str] = {}
        self._state_store: SigmaRuleStateStore | None = None

    def load_rules(
        self, paths: Sequence[Path], *, source_kind: str = "bundled"
    ) -> None:
        """Load, compile, and index Sigma rules from YAML file paths.

        Invalid rules are logged as warnings and skipped. Rules with a
        ``rule_id`` already present in the index are skipped (first-loaded
        wins) and a WARNING is logged — see :class:`SigmaRuleCollisionError`.

        Security: callers must ensure paths are within a trusted directory.
        This method does not enforce path boundaries — it reads whatever
        paths are given. Use S-030's validated rule loading for user-supplied
        rule directories.
        """
        for path in paths:
            try:
                yaml_text = path.read_text()
                rule = SigmaRule.from_yaml(yaml_text)
                self._pipeline.apply(rule)
                compiled = compile_rule(rule)
                if compiled.rule_id in self._yaml_source:
                    logger.warning(
                        "Skipping Sigma rule with duplicate rule_id %s (path=%s)",
                        compiled.rule_id,
                        path,
                    )
                    continue
                self._index.setdefault(compiled.logsource_key, []).append(compiled)
                self._yaml_source[compiled.rule_id] = yaml_text
                self._source_kind[compiled.rule_id] = source_kind
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

        # Snapshot the disabled set once so the loop sees a coherent view
        # even if a concurrent toggle swaps the reference mid-iteration.
        disabled = self._disabled_rule_ids
        event_dict = _event_to_dict(event)
        alerts: list[Alert] = []

        for compiled in candidates:
            if compiled.rule_id in disabled:
                continue
            try:
                if match_event(compiled, event_dict):
                    self._match_counts[compiled.rule_id] += 1
                    self._last_fired_ns[compiled.rule_id] = event.timestamp_ns
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

    def iter_compiled_rules(self) -> Generator[CompiledRule, None, None]:
        """Yield every compiled rule in this engine.

        Iteration order groups rules by logsource key, then by insertion
        order inside each group. Callers must not rely on the exact
        ordering — treat it as an unordered set.
        """
        for rules in self._index.values():
            yield from rules

    # ------------------------------------------------------------------
    # S-151: runtime mutation API (toggle, list, validate, add)
    # ------------------------------------------------------------------

    def set_enabled(self, rule_id: str, enabled: bool) -> None:
        """Enable or disable *rule_id* atomically (copy-on-write).

        Unknown ``rule_id`` is a no-op — callers are expected to validate
        membership separately if they care.
        """
        with self._mutation_lock:
            current = self._disabled_rule_ids
            if enabled and rule_id in current:
                self._disabled_rule_ids = current - {rule_id}
            elif not enabled and rule_id not in current:
                self._disabled_rule_ids = current | {rule_id}

    def list_rules(self) -> list[dict[str, object]]:
        """Return a snapshot of every loaded rule with stats + flags."""
        out: list[dict[str, object]] = []
        disabled = self._disabled_rule_ids
        for rule in self.iter_compiled_rules():
            out.append(
                {
                    "rule_id": rule.rule_id,
                    "title": rule.rule_name,
                    "description": rule.description,
                    "severity": int(rule.severity.value),
                    "logsource_key": list(rule.logsource_key),
                    "attack_tactics": list(rule.attack_tactics),
                    "attack_techniques": list(rule.attack_techniques),
                    "enabled": rule.rule_id not in disabled,
                    "source": self._source_kind.get(rule.rule_id, "bundled"),
                    "yaml_source": self._yaml_source.get(rule.rule_id, ""),
                    "match_count_lifetime": int(self._match_counts[rule.rule_id]),
                    "last_fired_ns": self._last_fired_ns.get(rule.rule_id),
                }
            )
        return out

    def validate_rule(self, yaml_text: str) -> dict[str, object]:
        """Parse + compile *yaml_text* without persisting.

        Returns parsed metadata. Raises :class:`SigmaRuleValidationError`
        on failure (caller decides how to surface it).
        """
        rule = validate_yaml(yaml_text)
        return {
            "rule_id": compute_rule_id(rule),
            "title": rule.title or "",
            "logsource_key": [
                rule.logsource.category or "",
                rule.logsource.product or "",
                rule.logsource.service or "",
            ],
        }

    def add_rule(
        self,
        yaml_text: str,
        persist_path: Path,
        *,
        source_kind: str = "custom_uploaded",
    ) -> str:
        """Validate, persist, index, and return the new ``rule_id``.

        Raises :class:`SigmaRuleValidationError` (no persistence) on bad YAML.
        Raises :class:`SigmaRuleCollisionError` (no persistence) if the
        derived ``rule_id`` is already loaded — first-loaded wins.
        """
        rule = validate_yaml(yaml_text)
        rid = compute_rule_id(rule)

        with self._mutation_lock:
            if rid in self._yaml_source:
                raise SigmaRuleCollisionError(
                    rule_id=rid,
                    existing_source=self._source_kind.get(rid, "bundled"),
                )
            persist_path.parent.mkdir(parents=True, exist_ok=True)
            persist_path.write_text(yaml_text)

            compiled = compile_rule(rule)
            new_index = {k: list(v) for k, v in self._index.items()}
            new_index.setdefault(compiled.logsource_key, []).append(compiled)
            self._index = new_index
            self._rule_count += 1
            self._yaml_source[rid] = yaml_text
            self._source_kind[rid] = source_kind

        return rid

    async def attach_state_store(self, store: SigmaRuleStateStore) -> None:
        """Hydrate enabled flags + counters from *store* and remember it."""
        self._state_store = store
        states = await store.get_all()
        disabled = {sid for sid, s in states.items() if not s.enabled}
        with self._mutation_lock:
            self._disabled_rule_ids = frozenset(disabled)
        for rid, s in states.items():
            self._match_counts[rid] = s.match_count_lifetime
            if s.last_fired_ns is not None:
                self._last_fired_ns[rid] = s.last_fired_ns

    async def flush_counters(self) -> None:
        """Persist accumulated match counters to the state store and reset.

        No-op when no state store is attached or counters are empty.
        """
        if self._state_store is None or not self._match_counts:
            return
        deltas: dict[str, tuple[int, int]] = {
            rid: (n, self._last_fired_ns.get(rid, 0))
            for rid, n in self._match_counts.items()
            if n > 0
        }
        await self._state_store.increment_counts(deltas)
        self._match_counts.clear()


def _create_sigma_alert(compiled: CompiledRule, event: SeerflowEvent) -> Alert:
    """Create an Alert from a matching Sigma rule and triggering event."""
    entity_refs = event.entity_refs
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
        entity_value=primary_entity_value(event),
        entity_type=infer_entity_type(event),
        contributing_events=(event.event_id,),
        mitre_tactics=compiled.attack_tactics,
        mitre_techniques=compiled.attack_techniques,
        dedup_key=(
            f"sigma:{compiled.rule_name}:{event.source_type}"
            f":{entity_refs[0] if entity_refs else ''}"
        ),
    )
