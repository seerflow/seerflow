"""FalkorDB-backed :class:`GraphBackend` adapter (S-155-F1).

FalkorDB is a Redis fork that speaks openCypher with GraphBLAS-accelerated
graph algorithms. This adapter implements the same :class:`GraphBackend`
Protocol surface as :class:`InMemoryIgraphBackend` so the pipeline +
storage layer stay decoupled from the concrete backend.

Connection model
----------------
The adapter is constructed in one of two ways:

* :meth:`FalkorDBGraphBackend.connect` — production entry point. Takes a
  ``falkor://host:port`` URL (or ``falkors://`` for TLS), lazily imports
  ``falkordb.asyncio.FalkorDB``, and connects.
* ``FalkorDBGraphBackend(client=...)`` — direct injection. Used by the
  unit tests with an ``AsyncMock`` client. Production code goes through
  :meth:`connect`.

The lazy import is wrapped in :func:`_load_falkordb`, which converts the
``ImportError`` into a :class:`seerflow.config.ConfigError` with an
actionable install hint (``uv sync --extra graph-falkordb``). This
mirrors the pattern :func:`seerflow.storage.factory.connect_storage`
uses for the ``postgres`` extra.

Cypher schema
-------------
* Entity vertices are ``(:Entity {name: <entity_id>})``. ``MERGE`` is
  used everywhere so re-inserting an existing entity is idempotent.
* Relationships use the literal ``rel_type`` string as the relationship
  type label, with three properties:

  * ``first_seen`` (``min`` of all observations)
  * ``last_seen`` (``max`` of all observations)
  * ``event_count`` (incremented on every observation)

* The fixed graph name is ``"seerflow"``. Per-graph multi-tenancy is
  intentionally out of scope for the first cut.

Coverage discipline
-------------------
This module is **not** added to the project-wide coverage ``omit`` list
(unlike ``storage/postgres*.py``). Unit tests with a mocked client cover
every line. The Docker-gated integration test
(``tests/integration/test_falkordb_integration.py``) validates only the
wire format against a live FalkorDB container and is opt-in via the
``requires_falkordb`` pytest marker.
"""

from __future__ import annotations

from typing import Any

from seerflow.config import ConfigError
from seerflow.models.query import EntityRelation

# ---------------------------------------------------------------------------
# Lazy import wrapper
# ---------------------------------------------------------------------------


_GRAPH_NAME = "seerflow"

_MISSING_FALKORDB_MSG = (
    "FalkorDB graph backend requires the 'graph-falkordb' extra. "
    "Install with: uv sync --extra graph-falkordb"
)


def _real_import_falkordb() -> Any:  # pragma: no cover - graph-falkordb extra only
    """Actual ``import falkordb.asyncio.FalkorDB`` — patched in unit tests."""
    from falkordb.asyncio import FalkorDB

    return FalkorDB


def _load_falkordb() -> Any:
    """Return the ``FalkorDB`` async class or raise :class:`ConfigError`."""
    try:
        return _real_import_falkordb()
    except ImportError as exc:
        raise ConfigError(_MISSING_FALKORDB_MSG) from exc


# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------


# add_edge — MERGE the two nodes + the relationship; first/last/count
# fold in using SET ... = CASE WHEN coalesce(...) IS NULL.
_ADD_EDGE_CYPHER_TEMPLATE = """
MERGE (s:Entity {{name: $src}})
MERGE (t:Entity {{name: $tgt}})
MERGE (s)-[r:`{rel_type}`]->(t)
ON CREATE SET r.first_seen = $ts, r.last_seen = $ts, r.event_count = 1
ON MATCH  SET r.first_seen = CASE WHEN r.first_seen < $ts THEN r.first_seen ELSE $ts END,
              r.last_seen  = CASE WHEN r.last_seen  > $ts THEN r.last_seen  ELSE $ts END,
              r.event_count = coalesce(r.event_count, 0) + 1
"""

_LOAD_EDGE_CYPHER_TEMPLATE = """
MERGE (s:Entity {{name: $src}})
MERGE (t:Entity {{name: $tgt}})
MERGE (s)-[r:`{rel_type}`]->(t)
SET r.first_seen = $first, r.last_seen = $last, r.event_count = $count
"""

_CLEAR_CYPHER = "MATCH (n) DETACH DELETE n"

_EXPORT_EDGES_CYPHER = (
    "MATCH (s:Entity)-[r]->(t:Entity) "
    "RETURN s.name, t.name, type(r), r.first_seen, r.last_seen, r.event_count"
)

_VERTEX_COUNT_CYPHER = "MATCH (n:Entity) RETURN count(n)"
_EDGE_COUNT_CYPHER = "MATCH ()-[r]->() RETURN count(r)"

_GET_RELATED_CYPHER = "MATCH (s:Entity {name: $src})-[r]-(n:Entity) RETURN n.name, type(r)"

_SHORTEST_PATH_CYPHER = (
    "MATCH p = shortestPath((s:Entity {name: $src})-[*..15]-(t:Entity {name: $tgt})) "
    "RETURN [n IN nodes(p) | n.name]"
)


def _neighbors_cypher(rel_types: tuple[str, ...] | None, depth: int) -> str:
    """Build the neighbours cypher.

    ``rel_types`` is restricted via ``WHERE type(r) IN [...]`` instead of
    interpolated as a relationship-type pattern so the cypher stays a
    single string (depth-2+ patterns get noisy fast). Strings are
    sanitised by quoting only — no user-supplied identifiers reach the
    cypher unsanitised.
    """
    depth = max(1, int(depth))
    if rel_types:
        # Whitelist: backtick-wrap each type identifier; reject any embedded
        # backtick so the query stays unforgeable.
        for rt in rel_types:
            if "`" in rt:
                msg = f"invalid rel_type {rt!r}: backticks are not allowed"
                raise ValueError(msg)
        rel_list = ", ".join(f"'{rt}'" for rt in rel_types)
        return (
            f"MATCH (s:Entity {{name: $src}})-[r*1..{depth}]-(n:Entity) "
            f"WHERE all(rel IN r WHERE type(rel) IN [{rel_list}]) "
            f"AND n.name <> $src "
            f"RETURN DISTINCT n.name"
        )
    return (
        f"MATCH (s:Entity {{name: $src}})-[*1..{depth}]-(n:Entity) "
        f"WHERE n.name <> $src "
        f"RETURN DISTINCT n.name"
    )


def _subgraph_nodes_cypher(depth: int) -> str:
    depth = max(1, int(depth))
    return f"MATCH (s:Entity {{name: $src}})-[*0..{depth}]-(n:Entity) RETURN DISTINCT n.name"


_SUBGRAPH_EDGES_CYPHER = (
    "MATCH (s:Entity)-[r]->(t:Entity) "
    "WHERE s.name IN $names AND t.name IN $names "
    "RETURN s.name, t.name, type(r)"
)


def _validate_rel_type(rel_type: str) -> str:
    """Reject relationship types containing characters that break cypher.

    FalkorDB uses backticked relationship-type literals. Embedded
    backticks would allow injection; reject them at the boundary.
    """
    if "`" in rel_type:
        msg = f"invalid rel_type {rel_type!r}: backticks are not allowed"
        raise ValueError(msg)
    return rel_type


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class FalkorDBGraphBackend:
    """:class:`GraphBackend` adapter over the FalkorDB async client.

    Construct directly with a pre-built client (used by tests), or via
    :meth:`connect` for production wiring.
    """

    __slots__ = ("_client", "_edge_count", "_graph", "_vertex_count")

    def __init__(self, *, client: Any) -> None:
        self._client = client
        self._graph = client.select_graph(_GRAPH_NAME)
        self._vertex_count = 0
        self._edge_count = 0

    @classmethod
    async def connect(cls, *, url: str) -> FalkorDBGraphBackend:
        """Connect to a FalkorDB instance and return a ready adapter."""
        falkor_cls = _load_falkordb()
        client = falkor_cls.from_url(url)
        return cls(client=client)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying client; safe to call multiple times."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        rel = _validate_rel_type(rel_type)
        cypher = _ADD_EDGE_CYPHER_TEMPLATE.format(rel_type=rel)
        await self._graph.query(
            cypher,
            params={"src": source_id, "tgt": target_id, "ts": timestamp_ns},
        )

    async def load(
        self,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        """Wipe the graph and bulk-insert ``rows`` (matches :class:`EntityGraph.load`)."""
        await self._graph.query(_CLEAR_CYPHER)
        for src, tgt, rel_type, first, last, count in rows:
            rel = _validate_rel_type(rel_type)
            cypher = _LOAD_EDGE_CYPHER_TEMPLATE.format(rel_type=rel)
            await self._graph.query(
                cypher,
                params={
                    "src": src,
                    "tgt": tgt,
                    "first": first,
                    "last": last,
                    "count": count,
                },
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_neighbors(
        self,
        entity_id: str,
        *,
        rel_types: tuple[str, ...] | None = None,
        depth: int = 1,
    ) -> list[dict[str, str]]:
        cypher = _neighbors_cypher(rel_types, depth)
        result = await self._graph.query(cypher, params={"src": entity_id})
        return [{"entity_id": _first(row)} for row in result.result_set]

    async def shortest_path(self, source_id: str, target_id: str) -> list[str]:
        result = await self._graph.query(
            _SHORTEST_PATH_CYPHER,
            params={"src": source_id, "tgt": target_id},
        )
        if not result.result_set:
            return []
        first_row = result.result_set[0]
        if not first_row or not first_row[0]:
            return []
        return [str(node) for node in first_row[0]]

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]:
        nodes_result = await self._graph.query(
            _subgraph_nodes_cypher(depth),
            params={"src": entity_id},
        )
        nodes: list[str] = [_first(row) for row in nodes_result.result_set]
        if not nodes:
            return ([], [])
        edges_result = await self._graph.query(
            _SUBGRAPH_EDGES_CYPHER,
            params={"names": nodes},
        )
        edges: list[dict[str, str]] = [
            {
                "source_id": str(row[0]),
                "target_id": str(row[1]),
                "rel_type": str(row[2]),
            }
            for row in edges_result.result_set
        ]
        return (nodes, edges)

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        result = await self._graph.query(_GET_RELATED_CYPHER, params={"src": entity_uuid})
        relations: list[EntityRelation] = []
        for row in result.result_set:
            neighbor_id = str(row[0])
            rel_type = str(row[1]) if row[1] else ""
            if not rel_type:
                continue
            relations.append(
                EntityRelation(
                    entity_uuid=neighbor_id,
                    entity_type="",
                    entity_value="",
                    relation_type=rel_type,
                )
            )
        return relations

    async def export_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]:
        result = await self._graph.query(_EXPORT_EDGES_CYPHER)
        return [
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                int(row[3]),
                int(row[4]),
                int(row[5]),
            )
            for row in result.result_set
        ]

    async def refresh_counts(self) -> None:
        """Update cached ``vertex_count`` / ``edge_count`` from the server."""
        v_res = await self._graph.query(_VERTEX_COUNT_CYPHER)
        e_res = await self._graph.query(_EDGE_COUNT_CYPHER)
        self._vertex_count = int(v_res.result_set[0][0]) if v_res.result_set else 0
        self._edge_count = int(e_res.result_set[0][0]) if e_res.result_set else 0

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def edge_count(self) -> int:
        return self._edge_count


def _first(row: list[Any]) -> str:
    """Helper: pull the first scalar out of a single-column result row."""
    return str(row[0])
