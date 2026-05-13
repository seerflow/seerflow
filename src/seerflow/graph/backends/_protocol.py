"""Runtime-checkable ``GraphBackend`` Protocol for entity-graph backends (S-155).

The Protocol carves a narrow, async-friendly surface over the entity
graph so the rest of the pipeline can depend on it instead of the
concrete :class:`seerflow.graph.entity_graph.EntityGraph`. Three backends
target this Protocol:

* :class:`seerflow.graph.backends.InMemoryIgraphBackend` — default,
  wraps the in-process igraph (this PR).
* FalkorDB adapter — Redis-fork with openCypher (S-155-F1, deferred).
* PostgreSQL AGE adapter — Cypher-in-SQL via asyncpg (S-155-F2, deferred).

All Protocol methods are declared ``async`` so the same surface survives
both the in-memory wrapper (trivial coroutines) and the genuinely async
external backends — no sync/async fork.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from seerflow.models.query import EntityRelation


@runtime_checkable
class GraphBackend(Protocol):  # pragma: no cover - structural Protocol
    """Pluggable entity-graph backend."""

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        """Upsert a directed typed edge between two entities."""
        ...

    async def get_neighbors(
        self,
        entity_id: str,
        *,
        rel_types: tuple[str, ...] | None = None,
        depth: int = 1,
    ) -> list[dict[str, str]]:
        """Return neighbours reachable within ``depth`` hops."""
        ...

    async def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str]:
        """Return the shortest undirected path as a list of entity IDs."""
        ...

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Return ``(nodes, edges)`` within ``depth`` hops of *entity_id*."""
        ...

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        """Return entities related to *entity_uuid* via the graph."""
        ...

    async def load(
        self,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        """Populate the backend from ``(src, tgt, rel, first, last, count)`` rows."""
        ...

    async def export_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        """Export all edges as storage-ready tuples."""
        ...

    @property
    def vertex_count(self) -> int:
        """Number of unique entity vertices."""
        ...

    @property
    def edge_count(self) -> int:
        """Number of relationship edges."""
        ...
