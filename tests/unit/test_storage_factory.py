"""Tests for seerflow.storage.connect_storage factory (S-169, S-073)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from seerflow.config import ConfigError, StorageConfig
from seerflow.storage import StorageBackend, connect_storage
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path


class TestConnectStorage:
    async def test_sqlite_returns_sqlite_backend(self, tmp_path: Path) -> None:
        """Returned value must satisfy both the composite Protocol and the
        concrete SqliteBackend class — dual compatibility (S-198 AC #8)."""
        cfg = StorageConfig(backend="sqlite", data_dir=str(tmp_path))
        storage = await connect_storage(cfg)
        try:
            assert isinstance(storage, StorageBackend)
            assert isinstance(storage, SqliteBackend)
        finally:
            await storage.close()

    async def test_unknown_backend_raises_value_error(self) -> None:
        cfg = StorageConfig(backend="redis")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="redis"):
            await connect_storage(cfg)


class TestPluginBackendDispatch:
    """S-370: connect_storage resolves a storage-backend plugin by name."""

    async def test_plugin_backend_returns_plugin_instance(self) -> None:
        from seerflow.plugins.groups import PluginGroup
        from seerflow.plugins.records import LoadedPlugins, PluginRecord

        sentinel = object()
        loaded = LoadedPlugins(
            records=(
                PluginRecord(
                    group=PluginGroup.STORAGE_BACKENDS,
                    name="acme-store",
                    distribution="acme",
                    version="1.0.0",
                    instance=sentinel,
                ),
            )
        )
        cfg = StorageConfig(backend="acme-store")  # type: ignore[arg-type]
        result = await connect_storage(cfg, plugins=loaded)
        assert result is sentinel

    async def test_plugin_prefix_is_stripped_before_lookup(self) -> None:
        from seerflow.plugins.groups import PluginGroup
        from seerflow.plugins.records import LoadedPlugins, PluginRecord

        sentinel = object()
        loaded = LoadedPlugins(
            records=(
                PluginRecord(
                    group=PluginGroup.STORAGE_BACKENDS,
                    name="acme-store",
                    distribution="acme",
                    version="1.0.0",
                    instance=sentinel,
                ),
            )
        )
        cfg = StorageConfig(backend="plugin:acme-store")
        result = await connect_storage(cfg, plugins=loaded)
        assert result is sentinel

    async def test_unknown_plugin_backend_raises_config_error(self) -> None:
        from seerflow.plugins.groups import PluginGroup
        from seerflow.plugins.records import LoadedPlugins, PluginRecord

        loaded = LoadedPlugins(
            records=(
                PluginRecord(
                    group=PluginGroup.STORAGE_BACKENDS,
                    name="acme-store",
                    distribution="acme",
                    version="1.0.0",
                    instance=object(),
                ),
            )
        )
        cfg = StorageConfig(backend="missing-store")  # type: ignore[arg-type]
        with pytest.raises(ConfigError, match="acme-store"):
            await connect_storage(cfg, plugins=loaded)

    async def test_builtin_backend_ignores_supplied_plugins(self, tmp_path: Path) -> None:
        """A built-in backend name resolves to the built-in even with plugins set."""
        from seerflow.plugins.records import LoadedPlugins

        cfg = StorageConfig(backend="sqlite", data_dir=str(tmp_path))
        storage = await connect_storage(cfg, plugins=LoadedPlugins())
        try:
            assert isinstance(storage, SqliteBackend)
        finally:
            await storage.close()


class TestPostgresFactoryDispatch:
    """S-073: factory dispatches to PostgresBackend with graceful absence."""

    async def test_missing_asyncpg_raises_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate asyncpg not installed by stubbing the import to fail.

        The factory's lazy ``import asyncpg`` lives inside
        ``PostgresBackend.connect``; setting ``sys.modules['asyncpg'] = None``
        is the canonical way to force ``ImportError`` without touching the
        actual asyncpg package on disk. The ``seerflow.storage.postgres``
        module is *not* purged — purging it forces a re-import that
        creates a second module instance and breaks subsequent tests'
        ``monkeypatch.setattr(pg_mod, ...)`` patches.
        """
        monkeypatch.setitem(sys.modules, "asyncpg", None)

        cfg = StorageConfig(backend="postgresql", postgresql_url="postgresql://x/y")
        with pytest.raises(ConfigError, match="uv sync --extra postgres"):
            await connect_storage(cfg)

    async def test_missing_dsn_raises_config_error(self) -> None:
        cfg = StorageConfig(backend="postgresql", postgresql_url="")
        with pytest.raises(ConfigError, match="postgresql_url is required"):
            await connect_storage(cfg)

    async def test_dispatch_calls_postgres_backend_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When asyncpg is present the factory routes to PostgresBackend.connect()."""
        from seerflow.storage import postgres as pg_mod

        calls: list[StorageConfig] = []

        class _FakePostgresBackend:
            @classmethod
            async def connect(cls, config: StorageConfig) -> str:
                calls.append(config)
                return "sentinel-backend"

        monkeypatch.setattr(pg_mod, "PostgresBackend", _FakePostgresBackend)
        cfg = StorageConfig(backend="postgresql", postgresql_url="postgresql://x/y")
        result = await connect_storage(cfg)
        assert result == "sentinel-backend"
        assert len(calls) == 1
        assert calls[0].postgresql_url == "postgresql://x/y"
