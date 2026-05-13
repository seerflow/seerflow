"""Unit tests for :func:`seerflow.graph.factory.connect_graph` (S-155 Task 4 + S-155-F1)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import ConfigError, StorageConfig
from seerflow.graph.backends import GraphBackend, InMemoryIgraphBackend
from seerflow.graph.factory import connect_graph


class TestConnectGraphDefault:
    @pytest.mark.asyncio
    async def test_returns_in_memory_backend_for_igraph(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
        backend = await connect_graph(cfg)
        assert isinstance(backend, InMemoryIgraphBackend)
        assert isinstance(backend, GraphBackend)

    @pytest.mark.asyncio
    async def test_in_memory_backend_starts_empty(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
        backend = await connect_graph(cfg)
        assert backend.vertex_count == 0
        assert backend.edge_count == 0

    @pytest.mark.asyncio
    async def test_each_call_returns_fresh_backend(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
        first = await connect_graph(cfg)
        second = await connect_graph(cfg)
        assert first is not second


def _fake_falkor_class() -> Any:
    """Build a fake ``FalkorDB`` class whose ``from_url`` returns a stubbed client."""

    class _FakeFalkor:
        @classmethod
        def from_url(cls, url: str) -> _FakeFalkor:
            return cls()

        def select_graph(self, name: str) -> Any:
            graph = MagicMock()
            graph.query = AsyncMock()
            return graph

        async def aclose(self) -> None:
            return None

    return _FakeFalkor


class TestConnectGraphFalkorDB:
    """S-155-F1 — ``graph_backend == 'falkordb'`` returns a connected adapter."""

    @pytest.mark.asyncio
    async def test_returns_falkordb_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import seerflow.graph.falkordb_backend as falkor_mod

        monkeypatch.setattr(falkor_mod, "_load_falkordb", _fake_falkor_class)
        cfg = StorageConfig(
            backend="sqlite",
            graph_backend="falkordb",
            falkordb_url="falkor://localhost:6379",
        )
        backend = await connect_graph(cfg)
        assert isinstance(backend, falkor_mod.FalkorDBGraphBackend)
        assert isinstance(backend, GraphBackend)

    @pytest.mark.asyncio
    async def test_raises_config_error_when_url_empty(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="falkordb")
        with pytest.raises(ConfigError, match="falkordb_url"):
            await connect_graph(cfg)

    @pytest.mark.asyncio
    async def test_propagates_config_error_when_extra_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing ``falkordb`` package surfaces as ``ConfigError`` with the install hint."""
        import seerflow.graph.falkordb_backend as falkor_mod

        def _raise_import() -> Any:
            raise ImportError("No module named 'falkordb'")

        monkeypatch.setattr(falkor_mod, "_real_import_falkordb", _raise_import)
        cfg = StorageConfig(
            backend="sqlite",
            graph_backend="falkordb",
            falkordb_url="falkor://localhost:6379",
        )
        with pytest.raises(ConfigError, match="graph-falkordb"):
            await connect_graph(cfg)


def _fake_asyncpg_module() -> Any:
    """Build a fake ``asyncpg`` module whose ``create_pool`` returns a stubbed pool."""

    class _FakePool:
        def __init__(self) -> None:
            self._conn = _FakeConn()

        def acquire(self) -> Any:
            return _FakeAcquire(self._conn)

        async def close(self) -> None:
            return None

    class _FakeConn:
        async def execute(self, _sql: str, *_args: Any) -> str:
            return "OK"

        async def fetchval(self, _sql: str, *_args: Any) -> Any:
            return None  # graph not present -> bootstrap creates it

        async def fetch(self, _sql: str, *_args: Any) -> list[tuple[Any, ...]]:
            return []

    class _FakeAcquire:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        async def __aenter__(self) -> _FakeConn:
            return self._conn

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    class _FakeAsyncpg:
        @staticmethod
        async def create_pool(**_kwargs: Any) -> _FakePool:
            return _FakePool()

    return _FakeAsyncpg


class TestConnectGraphPostgresAGE:
    """S-155-F2 — ``graph_backend == 'postgres_age'`` returns a connected adapter."""

    @pytest.mark.asyncio
    async def test_returns_postgres_age_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import seerflow.graph.postgres_age_backend as age_mod

        monkeypatch.setattr(age_mod, "_load_asyncpg", _fake_asyncpg_module)
        cfg = StorageConfig(
            backend="postgresql",
            postgresql_url="postgresql://u:p@h/db",
            graph_backend="postgres_age",
        )
        backend = await connect_graph(cfg)
        assert isinstance(backend, age_mod.PostgresAGEGraphBackend)
        assert isinstance(backend, GraphBackend)

    @pytest.mark.asyncio
    async def test_raises_config_error_when_url_empty(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="postgres_age")
        with pytest.raises(ConfigError, match="postgresql_url"):
            await connect_graph(cfg)

    @pytest.mark.asyncio
    async def test_propagates_config_error_when_extra_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing ``asyncpg`` package surfaces as ``ConfigError`` with the install hint."""
        import seerflow.graph.postgres_age_backend as age_mod

        def _raise_import() -> Any:
            raise ImportError("No module named 'asyncpg'")

        monkeypatch.setattr(age_mod, "_real_import_asyncpg", _raise_import)
        cfg = StorageConfig(
            backend="postgresql",
            postgresql_url="postgresql://u:p@h/db",
            graph_backend="postgres_age",
        )
        with pytest.raises(ConfigError, match="graph-postgres-age"):
            await connect_graph(cfg)


class TestConnectGraphDefenceInDepth:
    @pytest.mark.asyncio
    async def test_raises_value_error_for_unknown_backend(self) -> None:
        """Defence-in-depth — config validation should catch this first.

        We bypass ``StorageConfig`` validation by constructing the dataclass
        with a forged ``graph_backend`` value (Python dataclasses do not
        enforce ``Literal`` at runtime), confirming the factory still fails
        loudly rather than returning a wrong backend.
        """
        cfg = StorageConfig(backend="sqlite")
        object.__setattr__(cfg, "graph_backend", "unknown_backend")
        with pytest.raises(ValueError, match="Unsupported"):
            await connect_graph(cfg)


class TestConnectGraphLogging:
    @pytest.mark.asyncio
    async def test_logs_active_backend_at_info_level(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
        with caplog.at_level(logging.INFO, logger="seerflow.graph.factory"):
            await connect_graph(cfg)
        assert any(
            "igraph" in rec.message and "graph backend" in rec.message.lower()
            for rec in caplog.records
        )
