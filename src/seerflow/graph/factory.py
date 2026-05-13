"""Graph-backend factory — dispatches on ``StorageConfig.graph_backend`` (S-155).

The factory mirrors :func:`seerflow.storage.factory.connect_storage`:
operators select the entity-graph backend with one config key and the
factory hands back a connected :class:`GraphBackend`. The default branch
returns the in-memory igraph adapter — zero behaviour change for any
existing deployment.

Backend routing:

* ``"igraph"`` → in-memory ``InMemoryIgraphBackend`` (default).
* ``"falkordb"`` → :class:`FalkorDBGraphBackend` (S-155-F1). Requires
  the ``graph-falkordb`` optional extra and a non-empty
  ``storage.falkordb_url``. Missing extra surfaces as
  :class:`ConfigError` with an install hint.
* ``"postgres_age"`` → S-155-F2 (Cypher-over-asyncpg via Apache AGE),
  still deferred. Branch raises :class:`NotImplementedError`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from seerflow.config import ConfigError
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
        ConfigError: When ``graph_backend == "falkordb"`` and either the
            ``graph-falkordb`` extra is missing or ``falkordb_url`` is
            empty.
        NotImplementedError: When ``graph_backend == "postgres_age"`` —
            still tracked in S-155-F2.
        ValueError: For any other unknown value (config validation should
            catch this earlier; this is the defence-in-depth path).
    """
    backend = config.graph_backend
    _log.info("entity graph backend: %s", backend)

    if backend == "igraph":
        return InMemoryIgraphBackend()
    if backend == "falkordb":
        if not config.falkordb_url:
            msg = "storage.falkordb_url is required when storage.graph_backend == 'falkordb'"
            raise ConfigError(msg)
        from seerflow.graph.falkordb_backend import FalkorDBGraphBackend

        return await FalkorDBGraphBackend.connect(url=config.falkordb_url)
    if backend == "postgres_age":
        msg = (
            "PostgreSQL AGE graph backend is not yet implemented — "
            "tracked in S-155-F2. Use graph_backend: igraph (default) "
            "until the follow-up lands."
        )
        raise NotImplementedError(msg)
    msg = f"Unsupported storage.graph_backend: {backend!r}"
    raise ValueError(msg)
