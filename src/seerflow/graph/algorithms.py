"""Graph algorithms for entity structural analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.graph.entity_graph import EntityGraph


def compute_pagerank(graph: EntityGraph) -> dict[str, float]:
    """Compute PageRank importance scores for all entities.

    Returns a dict mapping entity_id to PageRank score.
    Scores sum to approximately 1.0.
    """
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    scores = ig.pagerank(directed=True)
    return {ig.vs[i]["name"]: scores[i] for i in range(ig.vcount())}


def compute_communities(graph: EntityGraph) -> dict[str, int]:
    """Compute Louvain community assignments for all entities.

    Returns a dict mapping entity_id to community_id (int).
    Uses undirected mode (Louvain requires undirected graphs).
    """
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    undirected = ig.as_undirected(mode="collapse")
    undirected.simplify()  # Remove self-loops and multi-edges for Louvain
    membership = undirected.community_multilevel().membership
    return {undirected.vs[i]["name"]: membership[i] for i in range(undirected.vcount())}


def compute_fan_out(graph: EntityGraph) -> dict[str, int]:
    """Count unique outgoing targets per entity."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {
        ig.vs[i]["name"]: len(set(ig.neighbors(i, mode="out")))
        for i in range(ig.vcount())
    }


def compute_fan_in(graph: EntityGraph) -> dict[str, int]:
    """Count unique incoming sources per entity."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {
        ig.vs[i]["name"]: len(set(ig.neighbors(i, mode="in")))
        for i in range(ig.vcount())
    }


def compute_betweenness(graph: EntityGraph) -> dict[str, float]:
    """Compute normalized betweenness centrality for all entities.

    High-betweenness entities are pivot points used as stepping stones.
    Uses undirected mode for path computation. Scores normalized to [0, 1].
    """
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    n = ig.vcount()
    # Normalize by (n-1)(n-2)/2 for undirected graphs
    denom = ((n - 1) * (n - 2)) / 2 if n > 2 else 1.0
    scores = ig.betweenness(directed=False)
    return {
        ig.vs[i]["name"]: scores[i] / denom if denom > 0 else 0.0
        for i in range(n)
    }


def compute_ego_graph_size(graph: EntityGraph) -> dict[str, int]:
    """Compute 1-hop unique neighbor count per entity (undirected)."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {
        ig.vs[i]["name"]: len(set(ig.neighbors(i, mode="all")))
        for i in range(ig.vcount())
    }
