"""Mutable holder for hot-swappable engine references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

_T = TypeVar("_T")


@dataclass
class EngineHolder(Generic[_T]):
    """Mutable wrapper allowing atomic engine replacement.

    Used to hold references to ``SigmaEngine`` and ``CorrelationEngine``
    so that a running pipeline handler reads the *current* engine at
    evaluation time, enabling hot-reload without restarting the pipeline.

    Thread safety: safe only within a single asyncio event loop thread.
    The watcher and handler both run as asyncio tasks on the same loop,
    so attribute assignment is effectively atomic under the GIL. Do not
    use from multiple OS threads without adding a lock.
    """

    engine: _T
