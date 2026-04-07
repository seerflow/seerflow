"""In-memory entity graph backed by igraph."""

from __future__ import annotations

import warnings

import igraph


class EntityGraph:
    """Directed multigraph for entity relationships.

    Wraps igraph.Graph with a string->int vertex map for O(1) UUID lookup.
    Edge attributes: rel_type, first_seen, last_seen, event_count.
    """

    __slots__ = ("_graph", "_vertex_map")

    def __init__(self) -> None:
        self._graph = igraph.Graph(directed=True)
        self._vertex_map: dict[str, int] = {}

    def _ensure_vertex(self, entity_id: str) -> int:
        """Return vertex index for *entity_id*, creating it if absent."""
        if entity_id not in self._vertex_map:
            idx: int = self._graph.vcount()
            self._graph.add_vertex(name=entity_id)
            self._vertex_map[entity_id] = idx
        return self._vertex_map[entity_id]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        """Add or update a directed edge between two entities.

        If an edge with the same (source, target, rel_type) already exists,
        update *last_seen* and increment *event_count* instead of creating a
        duplicate.
        """
        src_idx = self._ensure_vertex(source_id)
        tgt_idx = self._ensure_vertex(target_id)

        for eid in self._graph.incident(src_idx, mode="out"):
            edge = self._graph.es[eid]
            if edge.target == tgt_idx and edge["rel_type"] == rel_type:
                edge["first_seen"] = min(edge["first_seen"], timestamp_ns)
                edge["last_seen"] = max(edge["last_seen"], timestamp_ns)
                edge["event_count"] += 1
                return

        self._graph.add_edge(
            src_idx,
            tgt_idx,
            rel_type=rel_type,
            first_seen=timestamp_ns,
            last_seen=timestamp_ns,
            event_count=1,
        )

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------

    def get_edge_data(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
    ) -> dict[str, int] | None:
        """Return edge metadata or ``None`` if no matching edge exists."""
        src_idx = self._vertex_map.get(source_id)
        tgt_idx = self._vertex_map.get(target_id)
        if src_idx is None or tgt_idx is None:
            return None

        for eid in self._graph.incident(src_idx, mode="out"):
            edge = self._graph.es[eid]
            if edge.target == tgt_idx and edge["rel_type"] == rel_type:
                return {
                    "first_seen": edge["first_seen"],
                    "last_seen": edge["last_seen"],
                    "event_count": edge["event_count"],
                }
        return None

    def get_neighbors_with_rel(self, entity_id: str) -> list[tuple[str, str]]:
        """Return (neighbor_id, rel_type) pairs for immediate neighbors."""
        start = self._vertex_map.get(entity_id)
        if start is None:
            return []
        result: list[tuple[str, str]] = []
        for eid in self._graph.incident(start, mode="all"):
            edge = self._graph.es[eid]
            neighbor = edge.target if edge.source == start else edge.source
            result.append((self._graph.vs[neighbor]["name"], str(edge["rel_type"])))
        return result

    def get_neighbors(
        self,
        entity_id: str,
        *,
        rel_types: tuple[str, ...] | None = None,
        depth: int = 1,
    ) -> list[dict[str, str]]:
        """Return neighbor vertices reachable within *depth* hops.

        Traverses edges in both directions.  When *rel_types* is provided,
        only edges whose ``rel_type`` is in the tuple are followed.
        """
        start = self._vertex_map.get(entity_id)
        if start is None:
            return []

        visited: set[int] = {start}
        frontier: set[int] = {start}

        for _ in range(depth):
            next_frontier: set[int] = set()
            for vid in frontier:
                for eid in self._graph.incident(vid, mode="all"):
                    edge = self._graph.es[eid]
                    if rel_types and edge["rel_type"] not in rel_types:
                        continue
                    neighbor = edge.target if edge.source == vid else edge.source
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier

        visited.discard(start)
        return [{"entity_id": self._graph.vs[v]["name"]} for v in sorted(visited)]

    def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str]:
        """Return the shortest undirected path as a list of entity IDs.

        Returns an empty list when the vertices are disconnected or unknown.
        """
        src = self._vertex_map.get(source_id)
        tgt = self._vertex_map.get(target_id)
        if src is None or tgt is None:
            return []

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Couldn't reach some vertices",
                category=RuntimeWarning,
            )
            paths: list[list[int]] = self._graph.get_shortest_paths(src, to=tgt, mode="all")
        if not paths or not paths[0]:
            return []
        return [self._graph.vs[v]["name"] for v in paths[0]]

    def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Return nodes and edges within *depth* hops of *entity_id*."""
        neighbors = self.get_neighbors(entity_id, depth=depth)
        node_ids = [entity_id] + [n["entity_id"] for n in neighbors]
        vertex_indices = {self._vertex_map[nid] for nid in node_ids if nid in self._vertex_map}

        edges: list[dict[str, str]] = []
        for edge in self._graph.es:
            if edge.source in vertex_indices and edge.target in vertex_indices:
                edges.append(
                    {
                        "source_id": self._graph.vs[edge.source]["name"],
                        "target_id": self._graph.vs[edge.target]["name"],
                        "rel_type": edge["rel_type"],
                    }
                )
        return node_ids, edges

    # ------------------------------------------------------------------
    # Vertex attributes & algorithms
    # ------------------------------------------------------------------

    def set_vertex_attr(self, entity_id: str, key: str, value: object) -> None:
        """Set an attribute on a vertex. No-op if entity not in graph."""
        idx = self._vertex_map.get(entity_id)
        if idx is not None:
            self._graph.vs[idx][key] = value

    def get_vertex_attr(self, entity_id: str, key: str) -> object | None:
        """Get an attribute from a vertex. Returns None if not found."""
        idx = self._vertex_map.get(entity_id)
        if idx is None:
            return None
        try:
            result: object = self._graph.vs[idx][key]
        except KeyError:
            return None
        return result

    def run_algorithms(self) -> None:
        """Compute all graph algorithms and store as vertex attributes."""
        from seerflow.graph.algorithms import (
            compute_betweenness,
            compute_communities,
            compute_ego_graph_size,
            compute_fan_in,
            compute_fan_out,
            compute_pagerank,
        )

        for name, func in (
            ("pagerank", compute_pagerank),
            ("community_id", compute_communities),
            ("fan_out", compute_fan_out),
            ("fan_in", compute_fan_in),
            ("betweenness", compute_betweenness),
            ("ego_graph_size", compute_ego_graph_size),
        ):
            results = func(self)
            for entity_id, value in results.items():
                self.set_vertex_attr(entity_id, name, value)

    # ------------------------------------------------------------------
    # Bulk load / export (for storage round-trips)
    # ------------------------------------------------------------------

    def load(
        self,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        """Populate graph from storage rows.

        Each row is (source_id, target_id, rel_type, first_seen,
        last_seen, event_count).  Clears any existing graph state.
        """
        self._graph = igraph.Graph(directed=True)
        self._vertex_map.clear()

        for (
            source_id,
            target_id,
            rel_type,
            first_seen,
            last_seen,
            event_count,
        ) in rows:
            src_idx = self._ensure_vertex(source_id)
            tgt_idx = self._ensure_vertex(target_id)
            self._graph.add_edge(
                src_idx,
                tgt_idx,
                rel_type=rel_type,
                first_seen=first_seen,
                last_seen=last_seen,
                event_count=event_count,
            )

    def export_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        """Export all edges as storage-ready tuples."""
        return [
            (
                self._graph.vs[e.source]["name"],
                self._graph.vs[e.target]["name"],
                e["rel_type"],
                e["first_seen"],
                e["last_seen"],
                e["event_count"],
            )
            for e in self._graph.es
        ]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    def all_entity_ids(self) -> list[str]:
        """Return all entity IDs currently in the graph."""
        return list(self._vertex_map.keys())

    @property
    def vertex_count(self) -> int:
        """Number of unique entity vertices."""
        return int(self._graph.vcount())

    @property
    def edge_count(self) -> int:
        """Number of relationship edges."""
        return int(self._graph.ecount())
