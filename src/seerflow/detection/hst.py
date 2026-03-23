"""Half-Space Trees detector -- River HalfSpaceTrees wrapper."""

from __future__ import annotations

import pickle  # nosec B403 — needed for River model serialization
from typing import TYPE_CHECKING

from river import anomaly

if TYPE_CHECKING:
    from seerflow.config import DetectionConfig
    from seerflow.models import SeerflowEvent

_HST_HEIGHT = 8


def _extract_features(event: SeerflowEvent) -> dict[str, float]:
    """Extract feature vector from SeerflowEvent for HST input."""
    return {
        f"tid_{event.template_id}": 1.0,
        "entity_count": float(len(event.entity_refs)),
        "severity": float(event.severity_id.value),
        "param_count": float(len(event.template_params)),
        "msg_length": float(len(event.message)),
    }


class HSTDetector:
    """Streaming content anomaly detector using River Half-Space Trees."""

    __slots__ = ("_model",)

    def __init__(self, *, n_trees: int = 25, window_size: int = 1000, seed: int = 42) -> None:
        self._model = anomaly.HalfSpaceTrees(
            n_trees=n_trees,
            height=_HST_HEIGHT,
            window_size=window_size,
            seed=seed,
        )

    def score(self, event: SeerflowEvent) -> float:
        """Return anomaly score in [0.0, 1.0]."""
        features = _extract_features(event)
        raw: float = self._model.score_one(features)  # type: ignore[no-untyped-call]
        return max(0.0, min(1.0, raw))

    def learn(self, event: SeerflowEvent) -> None:
        """Update HST model incrementally."""
        features = _extract_features(event)
        self._model.learn_one(features)  # type: ignore[no-untyped-call]

    def serialize(self) -> bytes:
        """Serialize model state via pickle."""
        return pickle.dumps(self._model)

    def deserialize(self, data: bytes) -> None:
        """Restore model state from pickle bytes.

        Warning: pickle can execute arbitrary code. Only load from trusted sources.
        """
        self._model = pickle.loads(data)  # noqa: S301  # nosec B301


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
