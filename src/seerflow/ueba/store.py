"""BaselineStore: LRU-bounded per-entity baseline keeper."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

import msgspec

from seerflow.ueba.baseline import EntityBaseline, EntityType, UEBAParams, apply_event

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.protocols import ModelStore

_log = logging.getLogger("seerflow")

_STATE_KEY = "ueba.baselines"


class BaselineStore:
    """In-memory LRU of EntityBaseline keyed by entity UUID."""

    def __init__(self, *, params: UEBAParams, max_entities: int) -> None:
        self._params = params
        self._max_entities = max_entities
        self._baselines: OrderedDict[str, EntityBaseline] = OrderedDict()
        # S-082: cumulative LRU evictions since process start. The
        # persisted blob carries baselines only — the counter is reset
        # on every fresh process and reflects evictions observed since
        # this process booted (matches the semantics in DetectionEnsemble
        # and the other audited components; operator runbooks compute
        # deltas rather than absolutes).
        self._eviction_count = 0

    @property
    def params(self) -> UEBAParams:
        """Read-only accessor for the params this store was constructed with."""
        return self._params

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
            self._eviction_count += 1

    def __len__(self) -> int:
        return len(self._baselines)

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot."""
        return {
            "current": len(self._baselines),
            "max": self._max_entities,
            "evictions": self._eviction_count,
        }

    async def flush(self, model_store: ModelStore) -> None:
        """Persist the entire LRU as one msgpack blob.

        Swallows per-call failures (logs them) to match the ensemble's
        flush contract — pipeline lifecycle should not depend on a single
        persist attempt.
        """
        try:
            blob = msgspec.msgpack.encode(tuple(self._baselines.items()))
            await model_store.save_state(_STATE_KEY, blob)
        except Exception:
            _log.exception("UEBA baseline flush failed")

    async def restore(self, model_store: ModelStore) -> int:
        """Populate the LRU from persisted state. Returns count restored."""
        try:
            blob = await model_store.load_state(_STATE_KEY)
        except Exception:
            _log.exception("UEBA baseline load_state failed")
            return 0
        if not blob:
            return 0
        try:
            items = msgspec.msgpack.decode(
                blob,
                type=tuple[tuple[str, EntityBaseline], ...],
            )
        except Exception:
            _log.exception("UEBA baseline decode failed; starting empty")
            return 0
        self._baselines = OrderedDict(items)
        return len(self._baselines)
