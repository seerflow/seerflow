"""Detection protocol -- interface contract for all anomaly detectors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from seerflow.models import SeerflowEvent


@runtime_checkable
class Detector(Protocol):
    """Interface for streaming anomaly detectors.

    All detectors follow the score-then-learn pattern:
    1. ``score(event)`` -- score against model trained on past data
    2. ``learn(event)`` -- update model with the new event
    """

    def score(self, event: SeerflowEvent) -> float:
        """Return anomaly score in [0.0, 1.0]. Higher = more anomalous."""
        ...

    def learn(self, event: SeerflowEvent) -> None:
        """Update the model incrementally with a new event."""
        ...

    def serialize(self) -> bytes:
        """Serialize model state to bytes for persistence."""
        ...

    def deserialize(self, data: bytes) -> None:
        """Restore model state from bytes."""
        ...
