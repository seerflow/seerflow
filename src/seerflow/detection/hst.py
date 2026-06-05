"""Half-Space Trees detector -- River HalfSpaceTrees wrapper."""

from __future__ import annotations

import io
import pickle  # nosec B403 — needed for River model serialization
from typing import TYPE_CHECKING

from river import anomaly

if TYPE_CHECKING:
    from seerflow.config import DetectionConfig
    from seerflow.models import SeerflowEvent

_HST_HEIGHT = 8

# Restricted unpickler — only classes needed for HalfSpaceTrees round-trip
_HST_ALLOWED_CLASSES: frozenset[tuple[str, str]] = frozenset(
    {
        ("builtins", "tuple"),
        ("collections", "defaultdict"),
        ("functools", "partial"),
        ("random", "Random"),
        ("river.anomaly.hst", "HSTBranch"),
        ("river.anomaly.hst", "HSTLeaf"),
        ("river.anomaly.hst", "HalfSpaceTrees"),
    }
)


class _HSTUnpickler(pickle.Unpickler):
    """Restricted unpickler — refuses to deserialize classes not in the allowlist."""

    def find_class(self, module: str, name: str) -> type:
        if (module, name) not in _HST_ALLOWED_CLASSES:
            msg = f"Refused to deserialize {module}.{name}"
            raise pickle.UnpicklingError(msg)
        return super().find_class(module, name)  # type: ignore[no-any-return]


def _extract_features(event: SeerflowEvent) -> dict[str, float]:
    """Extract feature vector from SeerflowEvent for HST input."""
    return {
        f"tid_{event.template_id}": 1.0,
        "entity_count": float(
            len(event.related_ips) + len(event.related_users) + len(event.related_hosts)
        ),
        "severity": float(event.severity_id.value),
        "param_count": float(len(event.template_params)),
        "msg_length": float(len(event.message)),
    }


class HSTDetector:
    """Streaming content anomaly detector using River Half-Space Trees."""

    __slots__ = ("_feat_cache", "_feat_key", "_model")

    def __init__(self, *, n_trees: int = 10, window_size: int = 250, seed: int = 42) -> None:
        self._model = anomaly.HalfSpaceTrees(
            n_trees=n_trees,
            height=_HST_HEIGHT,
            window_size=window_size,
            seed=seed,
        )
        # S-356: one-entry feature cache. ``process_event`` calls ``score(event)``
        # then ``learn(event)`` for the SAME event; both extract the identical
        # feature dict. Cache the last event's features (keyed on event_id) so
        # the pair extracts once. Output (score + learned state) is bit-identical
        # — this only removes the duplicate pure-function call. Memory is O(1)
        # (a single dict for the most recent event).
        self._feat_key: object | None = None
        self._feat_cache: dict[str, float] = {}

    def _features_for(self, event: SeerflowEvent) -> dict[str, float]:
        """Extract (or reuse cached) features for *event*.

        The cache holds exactly the last event's features. Identical output to
        calling :func:`_extract_features` directly — it only avoids the
        duplicate extraction across a score/learn pair on the same event.
        """
        if self._feat_key != event.event_id:
            self._feat_cache = _extract_features(event)
            self._feat_key = event.event_id
        return self._feat_cache

    def score(self, event: SeerflowEvent) -> float:
        """Return anomaly score in [0.0, 1.0]."""
        features = self._features_for(event)
        raw: float = self._model.score_one(features)  # type: ignore[no-untyped-call]
        return max(0.0, min(1.0, raw))

    def learn(self, event: SeerflowEvent) -> None:
        """Update HST model incrementally."""
        features = self._features_for(event)
        self._model.learn_one(features)  # type: ignore[no-untyped-call]

    def serialize(self) -> bytes:
        """Serialize model state via pickle."""
        return pickle.dumps(self._model)

    def deserialize(self, data: bytes) -> None:
        """Restore model state from restricted pickle bytes.

        Uses a restricted unpickler that only allows the classes needed
        for HalfSpaceTrees reconstruction. Rejects arbitrary code execution
        payloads.
        """
        obj = _HSTUnpickler(io.BytesIO(data)).load()
        if not isinstance(obj, anomaly.HalfSpaceTrees):
            msg = f"Expected HalfSpaceTrees, got {type(obj).__name__}"
            raise TypeError(msg)
        self._model = obj


def get_hst_detector(
    source_type: str,
    config: DetectionConfig,
    registry: dict[str, HSTDetector],
) -> HSTDetector:
    """Get or create an HSTDetector for the given source type."""
    if source_type not in registry:
        registry[source_type] = HSTDetector(
            n_trees=config.hst_n_trees,
            window_size=config.hst_window_size,
        )
    return registry[source_type]
