"""Tests for EntityGraph igraph wrapper."""

from __future__ import annotations

from seerflow.graph.entity_graph import EntityGraph


class TestEntityGraphAddEdge:
    def test_add_edge_creates_vertices(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        assert g.vertex_count == 2

    def test_add_edge_creates_edge(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        assert g.edge_count == 1

    def test_add_duplicate_edge_updates_metadata(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "b", "has_ip", 2000)
        assert g.edge_count == 1
        data = g.get_edge_data("a", "b", "has_ip")
        assert data is not None
        assert data["last_seen"] == 2000
        assert data["event_count"] == 2

    def test_add_edge_preserves_first_seen(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "b", "has_ip", 2000)
        data = g.get_edge_data("a", "b", "has_ip")
        assert data is not None
        assert data["first_seen"] == 1000

    def test_add_edge_updates_first_seen_to_min(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "b", "has_ip", 500)
        data = g.get_edge_data("a", "b", "has_ip")
        assert data is not None
        assert data["first_seen"] == 500

    def test_different_rel_types_create_separate_edges(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "b", "logged_into", 1000)
        assert g.edge_count == 2


class TestEntityGraphQueries:
    def test_get_neighbors_depth_1(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "c", "logged_into", 1000)
        g.add_edge("c", "d", "has_ip", 1000)
        neighbors = g.get_neighbors("a", depth=1)
        ids = {n["entity_id"] for n in neighbors}
        assert ids == {"b", "c"}

    def test_get_neighbors_depth_2(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        neighbors = g.get_neighbors("a", depth=2)
        ids = {n["entity_id"] for n in neighbors}
        assert ids == {"b", "c"}

    def test_get_neighbors_with_rel_filter(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "c", "logged_into", 1000)
        neighbors = g.get_neighbors("a", rel_types=("has_ip",))
        assert len(neighbors) == 1
        assert neighbors[0]["entity_id"] == "b"

    def test_shortest_path(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        path = g.shortest_path("a", "c")
        assert path == ["a", "b", "c"]

    def test_shortest_path_disconnected(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("c", "d", "logged_into", 1000)
        path = g.shortest_path("a", "c")
        assert path == []

    def test_get_neighbors_unknown_vertex(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        neighbors = g.get_neighbors("unknown")
        assert neighbors == []

    def test_get_edge_data_nonexistent(self) -> None:
        g = EntityGraph()
        assert g.get_edge_data("a", "b", "has_ip") is None


class TestEntityGraphLoadExport:
    def test_load_from_rows(self) -> None:
        g = EntityGraph()
        rows = [
            ("a", "b", "has_ip", 1000, 2000, 5),
            ("b", "c", "logged_into", 1500, 1500, 1),
        ]
        g.load(rows)
        assert g.vertex_count == 3
        assert g.edge_count == 2
        data = g.get_edge_data("a", "b", "has_ip")
        assert data is not None
        assert data["event_count"] == 5

    def test_export_edges(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 2000)
        exported = g.export_edges()
        assert len(exported) == 2

    def test_get_subgraph_returns_nodes_and_edges(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        node_ids, edges = g.get_subgraph("a", depth=2)
        assert set(node_ids) == {"a", "b", "c"}
        assert len(edges) == 2

    def test_get_subgraph_unknown_entity(self) -> None:
        g = EntityGraph()
        node_ids, edges = g.get_subgraph("unknown")
        assert node_ids == ["unknown"]
        assert edges == []

    def test_get_edge_data_wrong_target(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("a", "c", "logged_into", 1000)
        assert g.get_edge_data("a", "c", "has_ip") is None

    def test_load_then_export_roundtrip(self) -> None:
        rows = [
            ("x", "y", "authenticated_from", 100, 200, 3),
        ]
        g = EntityGraph()
        g.load(rows)
        exported = g.export_edges()
        assert len(exported) == 1
        assert exported[0] == ("x", "y", "authenticated_from", 100, 200, 3)


class TestEntityGraphVertexAttrs:
    def test_set_and_get_vertex_attr(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.set_vertex_attr("a", "pagerank", 0.75)
        assert g.get_vertex_attr("a", "pagerank") == 0.75

    def test_get_vertex_attr_unknown_entity(self) -> None:
        g = EntityGraph()
        assert g.get_vertex_attr("unknown", "pagerank") is None

    def test_get_vertex_attr_unknown_key(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        assert g.get_vertex_attr("a", "nonexistent") is None

    def test_run_algorithms_sets_pagerank_and_community(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        g.run_algorithms()
        pr = g.get_vertex_attr("a", "pagerank")
        assert pr is not None
        assert isinstance(pr, float)
        cid = g.get_vertex_attr("a", "community_id")
        assert cid is not None
        assert isinstance(cid, int)

    def test_run_algorithms_sets_all_metrics(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        g.run_algorithms()
        # Original metrics
        assert g.get_vertex_attr("a", "pagerank") is not None
        assert g.get_vertex_attr("a", "community_id") is not None
        # New metrics
        assert g.get_vertex_attr("a", "fan_out") is not None
        assert g.get_vertex_attr("a", "fan_in") is not None
        assert g.get_vertex_attr("a", "betweenness") is not None
        assert g.get_vertex_attr("a", "ego_graph_size") is not None
