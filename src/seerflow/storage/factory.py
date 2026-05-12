"""Storage backend factory — dispatches on StorageConfig.backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from seerflow.config import ConfigError, StorageConfig
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from seerflow.storage.postgres import PostgresBackend

# Public union alias for the storage backend returned by
# :func:`connect_storage`. The two concrete backends expose the same
# Protocol surface (LogStore + AlertStore + ModelStore + EntityStore +
# GraphStore + SigmaRuleStateStore), so callers typically depend on a
# Protocol rather than this union. ``StorageBackend`` is exported for
# top-level wiring (CLI, pipeline) that holds onto the concrete instance.
StorageBackend = Union["SqliteBackend", "PostgresBackend"]


_MISSING_POSTGRES_MSG = (
    "PostgreSQL backend requires the 'postgres' extra. Install with: uv sync --extra postgres"
)


async def connect_storage(config: StorageConfig) -> StorageBackend:
    """Connect to the storage backend specified by ``config.backend``.

    Returns a connected backend instance. Callers are responsible for
    awaiting ``close()`` when done.

    Raises:
        ConfigError: When ``backend='postgresql'`` is requested but the
            ``postgres`` extra is not installed (asyncpg missing) or the
            DSN is empty.
        ValueError: For any other value of ``backend``.
    """
    backend = config.backend
    if backend == "sqlite":
        return await SqliteBackend.connect(config)
    if backend == "postgresql":
        try:
            from seerflow.storage.postgres import PostgresBackend
        except ImportError as exc:
            raise ConfigError(_MISSING_POSTGRES_MSG) from exc
        return await PostgresBackend.connect(config)
    raise ValueError(f"Unsupported storage.backend: {backend!r}")
