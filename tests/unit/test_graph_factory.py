"""Unit tests for :func:`seerflow.graph.factory.connect_graph` (S-155 Task 4)."""

from __future__ import annotations

import logging

import pytest

from seerflow.config import StorageConfig
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


class TestConnectGraphDeferred:
    @pytest.mark.asyncio
    async def test_raises_not_implemented_for_falkordb(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="falkordb")
        with pytest.raises(NotImplementedError) as exc_info:
            await connect_graph(cfg)
        assert "S-155-F1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_not_implemented_for_postgres_age(self) -> None:
        cfg = StorageConfig(backend="sqlite", graph_backend="postgres_age")
        with pytest.raises(NotImplementedError) as exc_info:
            await connect_graph(cfg)
        assert "S-155-F2" in str(exc_info.value)


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
