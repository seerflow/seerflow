"""Pluggable graph backends (S-155).

Foundation slice exposes the runtime-checkable :class:`GraphBackend`
Protocol and the default :class:`InMemoryIgraphBackend` adapter. The
FalkorDB and PostgreSQL-AGE backends are tracked under follow-up
stories S-155-F1 and S-155-F2 respectively.
"""

from __future__ import annotations

from seerflow.graph.backends._igraph import InMemoryIgraphBackend
from seerflow.graph.backends._protocol import GraphBackend

__all__ = ["GraphBackend", "InMemoryIgraphBackend"]
