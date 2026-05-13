"""Markov chain sequence anomaly detection via per-entity transition matrices.

Tracks template_id transitions per entity. Low-probability transitions
(novel or rare sequences) score as anomalous.

NOT thread-safe — designed for single event-loop operation.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import msgspec.msgpack

if TYPE_CHECKING:
    from seerflow.models import SeerflowEvent


class _EntityModel:
    """Per-entity Markov state: transition counts and previous template."""

    __slots__ = ("event_count", "prev_template", "total_from", "transitions")

    def __init__(self) -> None:
        self.prev_template: int = -1
        self.transitions: dict[int, dict[int, int]] = {}
        self.total_from: dict[int, int] = {}
        self.event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "prev_template": self.prev_template,
            "transitions": self.transitions,
            "total_from": self.total_from,
            "event_count": self.event_count,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> _EntityModel:
        m = _EntityModel()
        m.prev_template = d["prev_template"]
        m.transitions = {
            int(k): {int(k2): int(v2) for k2, v2 in v.items()} for k, v in d["transitions"].items()
        }
        m.total_from = {int(k): v for k, v in d["total_from"].items()}
        m.event_count = d["event_count"]
        return m


class MarkovDetector:
    """Per-entity Markov chain sequence anomaly detector.

    Implements the ``Detector`` protocol. Internally manages per-entity
    transition matrices keyed by ``entity_refs[0]``. Low-probability
    template_id transitions score as anomalous.

    Returns ``0.0`` for events with no entity, ``template_id == -1``,
    or entities still in warmup (fewer than ``min_events``).
    """

    __slots__ = (
        "_max_entities",
        "_min_events",
        "_models",
        "_smoothing",
    )

    def __init__(
        self,
        *,
        smoothing: float = 1e-6,
        min_events: int = 100,
        max_entities: int = 1000,
    ) -> None:
        if smoothing <= 0.0:
            msg = f"smoothing must be positive, got {smoothing!r}"
            raise ValueError(msg)
        if min_events < 1:
            msg = f"min_events must be >= 1, got {min_events!r}"
            raise ValueError(msg)
        if max_entities < 1:
            msg = f"max_entities must be >= 1, got {max_entities!r}"
            raise ValueError(msg)
        self._smoothing = smoothing
        self._min_events = min_events
        self._max_entities = max_entities
        self._models: OrderedDict[str, _EntityModel] = OrderedDict()

    @property
    def entity_count(self) -> int:
        """Return the number of tracked entity models."""
        return len(self._models)

    def score(self, event: SeerflowEvent) -> float:
        """Return sequence anomaly score for the event's primary entity."""
        entity = event.entity_refs[0] if event.entity_refs else None
        if entity is None or event.template_id == -1:
            return 0.0
        # Read-only lookup — does not create or touch LRU position.
        # learn() always follows score() in the ensemble pipeline.
        model = self._models.get(entity)
        if model is None:
            return 0.0
        if model.event_count < self._min_events or model.prev_template == -1:
            return 0.0
        prev = model.prev_template
        curr = event.template_id
        count = model.transitions.get(prev, {}).get(curr, 0)
        total = model.total_from.get(prev, 0)
        vocab = max(len(model.total_from), 1)
        denom = total + self._smoothing * vocab
        prob = (count + self._smoothing) / denom
        # Max surprisal: unseen transition with current training volume
        max_log = -math.log(self._smoothing / denom)
        if max_log <= 0.0:
            return 0.0
        return min(-math.log(prob) / max_log, 1.0)

    def learn(self, event: SeerflowEvent) -> None:
        """Update the per-entity transition model with the event."""
        entity = event.entity_refs[0] if event.entity_refs else None
        if entity is None or event.template_id == -1:
            return
        model = self._get_model(entity)
        curr = event.template_id
        if model.prev_template != -1:
            prev = model.prev_template
            if prev not in model.transitions:
                model.transitions[prev] = {}
            model.transitions[prev][curr] = model.transitions[prev].get(curr, 0) + 1
            model.total_from[prev] = model.total_from.get(prev, 0) + 1
        model.prev_template = curr
        model.event_count += 1

    def _get_model(self, entity_id: str) -> _EntityModel:
        """Return (or create) the model for an entity, with LRU eviction."""
        if entity_id in self._models:
            self._models.move_to_end(entity_id)
            return self._models[entity_id]
        if len(self._models) >= self._max_entities:
            self._models.popitem(last=False)
        model = _EntityModel()
        self._models[entity_id] = model
        return model

    def serialize(self) -> bytes:
        """Serialize all entity models to msgpack bytes."""
        state = {
            "smoothing": self._smoothing,
            "min_events": self._min_events,
            "max_entities": self._max_entities,
            "models": {entity_id: model.to_dict() for entity_id, model in self._models.items()},
        }
        return msgspec.msgpack.encode(state)

    def deserialize(self, data: bytes) -> None:
        """Restore all entity models from msgpack bytes."""
        state: dict = msgspec.msgpack.decode(data)  # type: ignore[type-arg]
        self._smoothing = state["smoothing"]
        self._min_events = state["min_events"]
        self._max_entities = state["max_entities"]
        self._models = OrderedDict()
        for entity_id, model_dict in state["models"].items():
            self._models[entity_id] = _EntityModel.from_dict(model_dict)
