"""Kill-chain state machine -- track per-entity ATT&CK tactic progression."""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.config import KillChainConfig
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_MAX_TACTICS_PER_ENTITY = 14  # 14 MITRE ATT&CK tactic categories


class KillChainTracker:
    """Track per-entity MITRE ATT&CK tactic progression.

    Alerts when an entity reaches ``tactic_threshold`` distinct tactics
    within ``window_seconds``.  Includes in-memory dedup so the threshold
    alert fires only once per entity until tactics change.
    """

    __slots__ = ("_config", "_entity_tactics", "_fired_entities", "_lru")

    def __init__(self, config: KillChainConfig) -> None:
        self._config = config
        # entity_uuid -> {tactic_name -> (first_seen_ns, alert_id)}
        self._entity_tactics: dict[str, dict[str, tuple[int, str]]] = {}
        self._lru: OrderedDict[str, None] = OrderedDict()
        self._fired_entities: set[str] = set()

    def record_alert(self, alert: Alert) -> list[Alert]:
        """Record tactics from an alert. Returns kill-chain alerts if threshold reached."""
        if not self._config.enabled or not alert.mitre_tactics or not alert.entity_uuid:
            return []

        entity_id = alert.entity_uuid
        self._evict_stale(entity_id, alert.timestamp_ns)

        tactics = self._entity_tactics.setdefault(entity_id, {})
        changed = False
        for tactic in alert.mitre_tactics:
            if tactic not in tactics and len(tactics) < _MAX_TACTICS_PER_ENTITY:
                tactics[tactic] = (alert.timestamp_ns, alert.alert_id)
                changed = True

        self._touch_entity(entity_id)
        self._enforce_max_entities()

        if not changed and entity_id in self._fired_entities:
            return []
        return self._check_threshold(entity_id, alert.timestamp_ns)

    def _evict_stale(self, entity_id: str, now_ns: int) -> None:
        """Remove tactics older than the configured window."""
        tactics = self._entity_tactics.get(entity_id)
        if tactics is None:
            return
        cutoff = now_ns - self._config.window_seconds * 1_000_000_000
        stale = [t for t, (ts, _) in tactics.items() if ts < cutoff]
        for t in stale:
            del tactics[t]
        if stale and entity_id in self._fired_entities:
            self._fired_entities.discard(entity_id)

    def _touch_entity(self, entity_id: str) -> None:
        """Move entity to end of LRU (O(1) via OrderedDict)."""
        self._lru.pop(entity_id, None)
        self._lru[entity_id] = None

    def _enforce_max_entities(self) -> None:
        """Evict oldest entities when over capacity."""
        while len(self._lru) > self._config.max_entities:
            oldest, _ = self._lru.popitem(last=False)
            self._entity_tactics.pop(oldest, None)
            self._fired_entities.discard(oldest)

    def _check_threshold(self, entity_id: str, timestamp_ns: int) -> list[Alert]:
        """Return a kill-chain alert if the entity has reached the tactic threshold."""
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel

        tactics = self._entity_tactics.get(entity_id, {})
        if len(tactics) < self._config.tactic_threshold:
            return []

        if entity_id in self._fired_entities:
            return []
        self._fired_entities.add(entity_id)

        sorted_tactics = sorted(tactics.items(), key=lambda x: x[1][0])
        tactic_names = tuple(t for t, _ in sorted_tactics)

        contributing_ids: list[uuid.UUID] = []
        for _, (_, aid) in sorted_tactics:
            with contextlib.suppress(ValueError, AttributeError):
                contributing_ids.append(uuid.UUID(aid))

        return [
            Alert(
                alert_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"kill-chain:{entity_id}:{timestamp_ns}",
                    )
                ),
                alert_type="correlation",
                timestamp_ns=timestamp_ns,
                severity_id=SeverityLevel.ERROR,
                rule_name="kill-chain-progression",
                description=(
                    f"Kill-chain: {len(tactic_names)} tactics for "
                    f"{entity_id[:8]}... — {', '.join(tactic_names)}"
                ),
                entity_uuid=entity_id,
                entity_value=entity_id[:16],
                entity_type="host",
                contributing_events=tuple(contributing_ids),
                mitre_tactics=tactic_names,
                mitre_techniques=(),
                risk_score=min(1.0, len(tactic_names) / 5.0),
                dedup_key=f"kill-chain:{entity_id}",
            )
        ]

    def get_entity_state(self, entity_id: str) -> dict[str, tuple[int, str]]:
        """Return a copy of the current tactic state for an entity."""
        return dict(self._entity_tactics.get(entity_id, {}))
