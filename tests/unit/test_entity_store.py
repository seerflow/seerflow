"""Tests for EntityStore Protocol implementation on SqliteBackend."""

from __future__ import annotations

import time

import pytest

from seerflow.storage.protocols import EntityStore


class TestEntityStoreProtocol:
    """Verify SqliteBackend satisfies EntityStore Protocol."""

    @pytest.fixture
    async def backend(self, tmp_path):
        from seerflow.config import StorageConfig
        from seerflow.storage.sqlite import SqliteBackend

        config = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "test.db"))
        b = await SqliteBackend.connect(config)
        yield b
        await b.close()

    async def test_isinstance_entity_store(self, backend) -> None:
        assert isinstance(backend, EntityStore)

    async def test_get_related_returns_list(self, backend) -> None:
        from seerflow.graph.entity_graph import EntityGraph

        graph = EntityGraph()
        backend.set_entity_graph(graph)
        result = await backend.get_related("nonexistent-uuid")
        assert isinstance(result, list)
        assert result == []

    async def test_get_related_with_graph_edges(self, backend) -> None:
        from seerflow.graph.entity_graph import EntityGraph
        from seerflow.models.entity import generate_ip_id, generate_user_id

        graph = EntityGraph()
        ip_uuid = str(generate_ip_id("10.0.1.1"))
        user_uuid = str(generate_user_id("admin", ""))
        graph.add_edge(user_uuid, ip_uuid, "authenticated_from", time.time_ns())
        backend.set_entity_graph(graph)

        related = await backend.get_related(user_uuid)
        assert len(related) >= 1
        assert any(r.entity_uuid == ip_uuid for r in related)

    async def test_get_related_without_graph_returns_empty(self, backend) -> None:
        result = await backend.get_related("some-uuid")
        assert result == []
