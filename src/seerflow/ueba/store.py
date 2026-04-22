"""BaselineStore: LRU-bounded per-entity baseline keeper."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

from seerflow.ueba.baseline import EntityBaseline, EntityType, UEBAParams, apply_event

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent


class BaselineStore:
    """In-memory LRU of EntityBaseline keyed by entity UUID."""

    def __init__(self, *, params: UEBAParams, max_entities: int) -> None:
        self._params = params
        self._max_entities = max_entities
        self._baselines: OrderedDict[str, EntityBaseline] = OrderedDict()

    def get(self, entity_uuid: str) -> EntityBaseline | None:
        """Read accessor. Does NOT promote LRU order."""
        return self._baselines.get(entity_uuid)

    def snapshot_and_learn(
        self,
        event: SeerflowEvent,
        *,
        entity_types: tuple[EntityType, ...],
    ) -> EntityBaseline | None:
        """Return the pre-update baseline for the first entity in
        ``event.entity_refs`` (or ``None``), then apply the update for every
        ``entity_ref`` paired with its type in ``entity_types``.
        """
        refs = event.entity_refs
        if not refs:
            return None
        snapshot = self._baselines.get(refs[0])
        for entity_uuid, entity_type in zip(refs, entity_types, strict=False):
            self._learn_one(entity_uuid, entity_type, event)
        return snapshot

    def _learn_one(
        self,
        entity_uuid: str,
        entity_type: EntityType,
        event: SeerflowEvent,
    ) -> None:
        prev = self._baselines.get(entity_uuid)
        new = apply_event(
            baseline=prev,
            entity_uuid=entity_uuid,
            entity_type=entity_type,
            event=event,
            params=self._params,
        )
        if entity_uuid in self._baselines:
            del self._baselines[entity_uuid]
        self._baselines[entity_uuid] = new
        if len(self._baselines) > self._max_entities:
            self._baselines.popitem(last=False)

    def __len__(self) -> int:
        return len(self._baselines)
