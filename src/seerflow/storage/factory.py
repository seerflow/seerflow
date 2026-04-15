"""Storage backend factory — dispatches on StorageConfig.backend."""

from __future__ import annotations

from seerflow.config import StorageConfig  # noqa: TC001
from seerflow.storage.sqlite import SqliteBackend


async def connect_storage(config: StorageConfig) -> SqliteBackend:
    """Connect to the storage backend specified by ``config.backend``.

    Returns a connected backend instance. Callers are responsible for
    awaiting ``close()`` when done.

    Raises:
        NotImplementedError: ``backend='postgresql'`` is reserved for a
            future story and not yet wired.
        ValueError: any other value for ``backend``.
    """
    backend = config.backend
    if backend == "sqlite":
        return await SqliteBackend.connect(config)
    if backend == "postgresql":
        raise NotImplementedError(
            "storage.backend='postgresql' is not yet implemented. "
            "Use 'sqlite' for now."
        )
    raise ValueError(f"Unsupported storage.backend: {backend!r}")
