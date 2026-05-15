"""Unit tests for :class:`InMemoryIgraphBackend` (S-155 Task 2)."""

from __future__ import annotations

from seerflow.graph.backends import GraphBackend, InMemoryIgraphBackend
from seerflow.graph.entity_graph import EntityGraph


class TestInMemoryIgraphBackendConformance:
    """The default backend must satisfy ``GraphBackend`` at runtime."""

    def test_backend_satisfies_graph_backend_protocol(self) -> None:
        backend = InMemoryIgraphBackend()
        assert isinstance(backend, GraphBackend)

    def test_backend_wraps_supplied_entity_graph(self) -> None:
        graph = EntityGraph()
        backend = InMemoryIgraphBackend(graph)
        assert backend.inner_graph is graph

    def test_backend_creates_default_graph_when_none(self) -> None:
        backend = InMemoryIgraphBackend()
        assert isinstance(backend.inner_graph, EntityGraph)


class TestInMemoryIgraphBackendMutation:
    async def test_add_edge_creates_vertices_and_edge(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "spawned_by", 1_000)
        assert backend.vertex_count == 2
        assert backend.edge_count == 1

    async def test_add_duplicate_edge_increments_count(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "uses", 1_000)
        await backend.add_edge("a", "b", "uses", 2_000)
        assert backend.edge_count == 1
        rows = await backend.export_edges()
        assert rows == [("a", "b", "uses", 1_000, 2_000, 2)]


class TestInMemoryIgraphBackendQueries:
    async def test_get_neighbors_walks_depth(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "x", 1)
        await backend.add_edge("b", "c", "x", 2)
        neighbours = await backend.get_neighbors("a", depth=2)
        assert sorted(n["entity_id"] for n in neighbours) == ["b", "c"]

    async def test_get_neighbors_filters_by_rel_types(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "x", 1)
        await backend.add_edge("a", "c", "y", 2)
        neighbours = await backend.get_neighbors("a", rel_types=("x",))
        assert [n["entity_id"] for n in neighbours] == ["b"]

    async def test_shortest_path_returns_path_through_wrapper(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "x", 1)
        await backend.add_edge("b", "c", "x", 2)
        path = await backend.shortest_path("a", "c")
        assert path == ["a", "b", "c"]

    async def test_get_subgraph_returns_nodes_and_edges(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "x", 1)
        await backend.add_edge("b", "c", "x", 2)
        nodes, edges = await backend.get_subgraph("a", depth=2)
        assert "a" in nodes
        assert "b" in nodes
        assert "c" in nodes
        assert any(e["source_id"] == "a" and e["target_id"] == "b" for e in edges)


class TestInMemoryIgraphBackendBulkRoundTrip:
    async def test_export_edges_storage_ready_tuple_shape(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("a", "b", "uses", 1_000)
        rows = await backend.export_edges()
        assert rows == [("a", "b", "uses", 1_000, 1_000, 1)]

    async def test_load_rebuilds_graph_from_rows(self) -> None:
        backend = InMemoryIgraphBackend()
        rows = [
            ("a", "b", "uses", 1, 5, 3),
            ("b", "c", "uses", 2, 6, 7),
        ]
        await backend.load(rows)
        assert backend.edge_count == 2
        assert (await backend.export_edges()) == rows


class TestInMemoryIgraphBackendRelations:
    async def test_get_related_returns_empty_when_entity_unknown(self) -> None:
        backend = InMemoryIgraphBackend()
        result = await backend.get_related("missing-uuid")
        assert result == []

    async def test_get_related_walks_graph_edges(self) -> None:
        backend = InMemoryIgraphBackend()
        await backend.add_edge("entity-a", "entity-b", "uses", 1_000)
        result = await backend.get_related("entity-a")
        # ``EntityRelation`` shape is opaque here; non-empty is enough.
        assert result != []
