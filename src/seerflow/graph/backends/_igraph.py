"""In-memory igraph-backed implementation of :class:`GraphBackend` (S-155).

The adapter wraps the synchronous :class:`EntityGraph` so the rest of
the pipeline can depend on the :class:`GraphBackend` Protocol surface
while the default backend keeps the zero-cost in-process igraph
implementation. Methods are declared ``async`` to match the Protocol;
the wrapped calls are sub-millisecond, so the trivial coroutine cost is
acceptable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.graph.entity_graph import EntityGraph

if TYPE_CHECKING:
    from seerflow.models.query import EntityRelation


class InMemoryIgraphBackend:
    """Async adapter over the in-process :class:`EntityGraph`."""

    __slots__ = ("_graph",)

    def __init__(self, graph: EntityGraph | None = None) -> None:
        self._graph = graph if graph is not None else EntityGraph()

    @property
    def inner_graph(self) -> EntityGraph:
        """Expose the underlying :class:`EntityGraph` for storage round-trips."""
        return self._graph

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        self._graph.add_edge(source_id, target_id, rel_type, timestamp_ns)

    async def get_neighbors(
        self,
        entity_id: str,
        *,
        rel_types: tuple[str, ...] | None = None,
        depth: int = 1,
    ) -> list[dict[str, str]]:
        return self._graph.get_neighbors(
            entity_id,
            rel_types=rel_types,
            depth=depth,
        )

    async def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str]:
        return self._graph.shortest_path(source_id, target_id)

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]:
        return self._graph.get_subgraph(entity_id, depth=depth)

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        # Inlined from ``storage.sqlite.get_related_from_graph`` so the
        # graph backend stays decoupled from any concrete storage module
        # (S-074 architectural guard).
        from seerflow.models.query import EntityRelation

        neighbors = self._graph.get_neighbors_with_rel(entity_uuid)
        if not neighbors:
            return []
        results: list[EntityRelation] = []
        for neighbor_id, rel_type in neighbors:
            if not rel_type:
                continue
            results.append(
                EntityRelation(
                    entity_uuid=neighbor_id,
                    entity_type="",
                    entity_value="",
                    relation_type=rel_type,
                )
            )
        return results

    async def load(
        self,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        self._graph.load(rows)

    async def export_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        return self._graph.export_edges()

    @property
    def vertex_count(self) -> int:
        return self._graph.vertex_count

    @property
    def edge_count(self) -> int:
        return self._graph.edge_count
