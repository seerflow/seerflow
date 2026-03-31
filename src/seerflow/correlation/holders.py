"""Mutable holder for hot-swappable engine references."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineHolder[T]:
    """Mutable wrapper allowing atomic engine replacement.

    Used to hold references to ``SigmaEngine`` and ``CorrelationEngine``
    so that a running pipeline handler reads the *current* engine at
    evaluation time, enabling hot-reload without restarting the pipeline.
    """

    engine: T
