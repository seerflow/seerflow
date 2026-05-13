"""Graph-backend factory — dispatches on ``StorageConfig.graph_backend`` (S-155).

The factory mirrors :func:`seerflow.storage.factory.connect_storage`:
operators select the entity-graph backend with one config key and the
factory hands back a connected :class:`GraphBackend`. The default branch
returns the in-memory igraph adapter — zero behaviour change for any
existing deployment.

Two backend names route to deferred follow-ups:

* ``"falkordb"`` → S-155-F1 (Redis-fork with openCypher).
* ``"postgres_age"`` → S-155-F2 (Cypher-over-asyncpg via Apache AGE).

Both branches raise :class:`NotImplementedError` with a message naming
the follow-up so operators understand why the value is reserved but not
yet usable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from seerflow.graph.backends import InMemoryIgraphBackend

if TYPE_CHECKING:
    from seerflow.config import StorageConfig
    from seerflow.graph.backends import GraphBackend

__all__ = ["connect_graph"]

_log = logging.getLogger(__name__)


async def connect_graph(config: StorageConfig) -> GraphBackend:
    """Return a connected :class:`GraphBackend` for the configured backend.

    Args:
        config: Storage configuration whose ``graph_backend`` field selects
            the implementation.

    Returns:
        A connected backend ready for use.

    Raises:
        NotImplementedError: When ``graph_backend`` names a backend whose
            implementation is deferred to a follow-up story (FalkorDB or
            PostgreSQL AGE).
        ValueError: For any other unknown value (config validation should
            catch this earlier; this is the defence-in-depth path).
    """
    backend = config.graph_backend
    _log.info("entity graph backend: %s", backend)

    if backend == "igraph":
        return InMemoryIgraphBackend()
    if backend == "falkordb":
        msg = (
            "FalkorDB graph backend is not yet implemented — tracked in "
            "S-155-F1. Use graph_backend: igraph (default) until the "
            "follow-up lands."
        )
        raise NotImplementedError(msg)
    if backend == "postgres_age":
        msg = (
            "PostgreSQL AGE graph backend is not yet implemented — "
            "tracked in S-155-F2. Use graph_backend: igraph (default) "
            "until the follow-up lands."
        )
        raise NotImplementedError(msg)
    msg = f"Unsupported storage.graph_backend: {backend!r}"
    raise ValueError(msg)
