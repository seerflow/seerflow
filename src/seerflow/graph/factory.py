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
* ``"postgres_age"`` → :class:`PostgresAGEGraphBackend` (S-155-F2).
  Requires the ``graph-postgres-age`` optional extra and a non-empty
  ``storage.postgresql_url`` (the same DSN the storage backend uses;
  AGE lives inside the same Postgres instance). Missing extra surfaces
  as :class:`ConfigError` with an install hint.
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
            empty. Same shape for ``graph_backend == "postgres_age"``
            with the ``graph-postgres-age`` extra and
            ``postgresql_url``.
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
        if not config.postgresql_url:
            msg = "storage.postgresql_url is required when storage.graph_backend == 'postgres_age'"
            raise ConfigError(msg)
        from seerflow.graph.postgres_age_backend import PostgresAGEGraphBackend

        return await PostgresAGEGraphBackend.connect(
            url=config.postgresql_url,
            min_size=config.postgresql_pool_min_size,
            max_size=config.postgresql_pool_max_size,
            command_timeout=config.postgresql_command_timeout_s,
        )
    msg = f"Unsupported storage.graph_backend: {backend!r}"
    raise ValueError(msg)
