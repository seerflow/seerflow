"""Storage backend factory — dispatches on StorageConfig.backend.

The factory returns the composite :class:`StorageBackend` Protocol from
:mod:`seerflow.storage.protocols`, so every call site stays backend-agnostic.
``StorageBackend`` is re-exported from this module for backwards
compatibility with imports written before the Protocol widening (S-198).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.config import ConfigError, StorageConfig
from seerflow.storage.protocols import StorageBackend
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from seerflow.plugins.records import LoadedPlugins

# ``StorageBackend`` is the composite ``@runtime_checkable`` Protocol from
# :mod:`seerflow.storage.protocols`. Re-exported here so the historical
# ``from seerflow.storage.factory import StorageBackend`` import path
# remains valid.
__all__ = ["StorageBackend", "connect_storage"]


_MISSING_POSTGRES_MSG = (
    "PostgreSQL backend requires the 'postgres' extra. Install with: uv sync --extra postgres"
)

# S-370: YAML selects a storage-backend plugin via ``backend: plugin:<name>``.
# The prefix is stripped before the inventory lookup, which keys plugins by
# their bare entry-point name. A bare name (no prefix) is also accepted for
# programmatic / directly-constructed configs.
_PLUGIN_BACKEND_PREFIX = "plugin:"


def _resolve_plugin_backend(backend: str, plugins: LoadedPlugins) -> StorageBackend:
    """Resolve a storage-backend plugin named ``backend`` (S-370 dispatch).

    Strips an optional ``plugin:`` prefix, then looks the bare name up in the
    loaded ``seerflow.storage_backends`` inventory. Raises ``ConfigError``
    when no plugin is registered under that name; the message lists the names
    that *are* available so operators can fix the config.
    """
    from seerflow.plugins.registration import find_storage_backend

    name = backend.removeprefix(_PLUGIN_BACKEND_PREFIX)
    instance = find_storage_backend(plugins, name)
    if instance is not None:
        return instance  # type: ignore[no-any-return]
    available = sorted(r.name for r in plugins.storage_backends)
    msg = (
        f"Unsupported storage.backend: {backend!r}; available storage-backend plugins: {available}"
    )
    raise ConfigError(msg)


async def connect_storage(
    config: StorageConfig,
    *,
    plugins: LoadedPlugins | None = None,
) -> StorageBackend:
    """Connect to the storage backend specified by ``config.backend``.

    Returns a connected backend instance typed as the composite
    :class:`~seerflow.storage.protocols.StorageBackend` Protocol so callers
    stay backend-agnostic. Callers are responsible for awaiting
    ``close()`` when done.

    ``plugins`` (S-370) is an optional :class:`LoadedPlugins` inventory used
    for storage-backend plugin dispatch: when ``config.backend`` is neither
    ``"sqlite"`` nor ``"postgresql"`` and ``plugins`` is supplied, the factory
    resolves the matching ``seerflow.storage_backends`` plugin and returns its
    instance. When ``plugins`` is ``None`` (the historical default) an unknown
    backend raises ``ValueError`` exactly as before.

    Raises:
        ConfigError: When ``backend='postgresql'`` is requested but the
            ``postgres`` extra is not installed (asyncpg missing), the DSN is
            empty, or a plugin backend name resolves to no registered plugin.
        ValueError: For an unknown backend when no ``plugins`` inventory is
            supplied.
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
    if plugins is not None:
        return _resolve_plugin_backend(backend, plugins)
    raise ValueError(f"Unsupported storage.backend: {backend!r}")
