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
    """Count unique outgoing targets per entity (directed out-degree)."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {ig.vs[i]["name"]: ig.degree(i, mode="out") for i in range(ig.vcount())}


def compute_fan_in(graph: EntityGraph) -> dict[str, int]:
    """Count unique incoming sources per entity (directed in-degree)."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {ig.vs[i]["name"]: ig.degree(i, mode="in") for i in range(ig.vcount())}


def compute_betweenness(graph: EntityGraph) -> dict[str, float]:
    """Compute normalized betweenness centrality for all entities.

    High-betweenness entities are pivot points used as stepping stones.
    Uses undirected mode for path computation.
    """
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    scores = ig.betweenness(directed=False)
    max_score = max(scores) if scores else 1.0
    if max_score == 0:
        max_score = 1.0
    return {ig.vs[i]["name"]: scores[i] / max_score for i in range(ig.vcount())}


def compute_ego_graph_size(graph: EntityGraph) -> dict[str, int]:
    """Compute 1-hop neighborhood size per entity (undirected)."""
    ig = graph._graph
    if ig.vcount() == 0:
        return {}
    return {ig.vs[i]["name"]: len(ig.neighbors(i, mode="all")) for i in range(ig.vcount())}
