"""Tests for graph algorithm functions."""

from __future__ import annotations

from seerflow.graph.algorithms import compute_communities, compute_pagerank
from seerflow.graph.entity_graph import EntityGraph


class TestComputePagerank:
    def test_returns_scores_for_all_vertices(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        scores = compute_pagerank(g)
        assert len(scores) == 3
        assert all(isinstance(v, float) for v in scores.values())

    def test_scores_sum_to_approximately_one(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        scores = compute_pagerank(g)
        assert abs(sum(scores.values()) - 1.0) < 0.01

    def test_hub_node_has_highest_score(self) -> None:
        g = EntityGraph()
        for i in range(5):
            g.add_edge(f"leaf-{i}", "hub", "has_ip", 1000)
        scores = compute_pagerank(g)
        assert scores["hub"] == max(scores.values())

    def test_empty_graph_returns_empty(self) -> None:
        g = EntityGraph()
        scores = compute_pagerank(g)
        assert scores == {}


class TestComputeCommunities:
    def test_disconnected_components_get_separate_ids(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("c", "d", "logged_into", 1000)
        communities = compute_communities(g)
        assert communities["a"] == communities["b"]
        assert communities["c"] == communities["d"]
        assert communities["a"] != communities["c"]

    def test_fully_connected_single_community(self) -> None:
        g = EntityGraph()
        g.add_edge("a", "b", "has_ip", 1000)
        g.add_edge("b", "c", "logged_into", 1000)
        g.add_edge("a", "c", "authenticated_from", 1000)
        communities = compute_communities(g)
        assert len(set(communities.values())) == 1

    def test_empty_graph_returns_empty(self) -> None:
        g = EntityGraph()
        communities = compute_communities(g)
        assert communities == {}
