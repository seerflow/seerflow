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
