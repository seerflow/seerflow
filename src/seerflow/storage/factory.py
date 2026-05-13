"""Storage backend factory — dispatches on StorageConfig.backend.

The factory returns the composite :class:`StorageBackend` Protocol from
:mod:`seerflow.storage.protocols`, so every call site stays backend-agnostic.
``StorageBackend`` is re-exported from this module for backwards
compatibility with imports written before the Protocol widening (S-198).
"""

from __future__ import annotations

from seerflow.config import ConfigError, StorageConfig
from seerflow.storage.protocols import StorageBackend
from seerflow.storage.sqlite import SqliteBackend

# ``StorageBackend`` is the composite ``@runtime_checkable`` Protocol from
# :mod:`seerflow.storage.protocols`. Re-exported here so the historical
# ``from seerflow.storage.factory import StorageBackend`` import path
# remains valid.
__all__ = ["StorageBackend", "connect_storage"]


_MISSING_POSTGRES_MSG = (
    "PostgreSQL backend requires the 'postgres' extra. Install with: uv sync --extra postgres"
)


async def connect_storage(config: StorageConfig) -> StorageBackend:
    """Connect to the storage backend specified by ``config.backend``.

    Returns a connected backend instance typed as the composite
    :class:`~seerflow.storage.protocols.StorageBackend` Protocol so callers
    stay backend-agnostic. Callers are responsible for awaiting
    ``close()`` when done.

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
