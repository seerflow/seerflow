"""PostgreSQL AGE-backed :class:`GraphBackend` adapter (S-155-F2).

Apache AGE is a PostgreSQL extension that adds openCypher graph queries on
top of vanilla Postgres. Operators already running Postgres for the
``LogStore`` / ``AlertStore`` / ``ModelStore`` can pick this backend to
keep the entity graph in the same database — no separate Redis-fork
process, no new failure domain, one backup and one restore.

Connection model
----------------
The adapter is constructed in one of two ways:

* :meth:`PostgresAGEGraphBackend.connect` — production entry point. Takes
  the same DSN as :class:`StorageConfig.postgresql_url` (S-073) along
  with the asyncpg pool knobs already validated on ``StorageConfig``.
  Lazily imports ``asyncpg`` and builds a dedicated pool whose ``setup``
  callback runs ``LOAD 'age'`` + ``SET search_path = ag_catalog, "$user",
  public`` on every checked-out connection.
* ``PostgresAGEGraphBackend(pool=...)`` — direct injection. Used by the
  unit tests with a forged asyncpg pool. Production code goes through
  :meth:`connect`.

The lazy import is wrapped in :func:`_load_asyncpg`, which converts the
``ImportError`` into a :class:`seerflow.config.ConfigError` with an
actionable install hint (``uv sync --extra graph-postgres-age``). This
mirrors :class:`seerflow.graph.falkordb_backend.FalkorDBGraphBackend` and
:func:`seerflow.storage.factory.connect_storage` exactly.

Why **not** reuse :class:`PostgresBackend`'s pool when
``storage.backend == "postgresql"``? Because the AGE pool's ``setup``
callback must run ``LOAD 'age'`` + ``SET search_path`` on every
checked-out connection. Reusing the storage pool would force AGE state on
non-graph queries that the storage backend issues. Two pools, same
database — minimal coupling at the cost of a few extra TCP connections.

Cypher schema
-------------
* Entity vertices are ``(:Entity {name: <entity_id>})``. ``MERGE`` is
  used everywhere so re-inserting an existing entity is idempotent.
* Relationships use the literal ``rel_type`` string as the relationship
  type label, with three properties:

  * ``first_seen`` (``min`` of all observations)
  * ``last_seen`` (``max`` of all observations)
  * ``event_count`` (incremented on every observation)

* The fixed graph name is ``"seerflow_graph"``. Per-graph multi-tenancy
  is intentionally out of scope for the first cut.

Cypher-in-SQL pattern
---------------------
AGE expresses graph queries inside a SQL ``SELECT * FROM cypher(...)``
wrapper:

.. code-block:: sql

    SELECT * FROM cypher(
        'seerflow_graph',
        $$ MATCH (s:Entity {name: $src}) RETURN s.name $$,
        $1::agtype
    ) AS (name agtype);

The parameter argument is a single ``agtype``-cast JSON object carrying
every Cypher placeholder. All other literal interpolations (graph name,
relationship-type filter list, depth bounds) must be validated to prevent
injection — :func:`_validate_rel_type` rejects backticks, single quotes,
and backslashes, matching the rule used by the FalkorDB adapter.

Coverage discipline
-------------------
Unit tests with a mocked asyncpg connection cover every line of this
module, so it is **not** added to the project-wide coverage ``omit``
list. The Docker-gated integration test
(``tests/integration/test_postgres_age_integration.py``) validates the
wire format against a real ``apache/age`` container and is opt-in via
the ``requires_postgres_age`` pytest marker.

Server requirements
-------------------
* PostgreSQL 12 or newer with the Apache AGE extension installed.
* The connection user needs ``CREATE EXTENSION`` privilege the first
  time (subsequent connections only ``LOAD 'age'``). For managed
  Postgres services that disallow user-installed extensions, the
  operator must enable AGE via the provider's extension allowlist
  before pointing Seerflow at the DSN.
"""

from __future__ import annotations

import json
from typing import Any

from seerflow.config import ConfigError
from seerflow.models.query import EntityRelation

# ---------------------------------------------------------------------------
# Lazy import wrapper
# ---------------------------------------------------------------------------


_GRAPH_NAME = "seerflow_graph"

_MISSING_ASYNCPG_MSG = (
    "PostgreSQL AGE graph backend requires the 'graph-postgres-age' extra. "
    "Install with: uv sync --extra graph-postgres-age"
)


def _real_import_asyncpg() -> Any:  # pragma: no cover - graph-postgres-age extra only
    """Actual ``import asyncpg`` — patched in unit tests."""
    import asyncpg

    return asyncpg


def _load_asyncpg() -> Any:
    """Return the ``asyncpg`` module or raise :class:`ConfigError`."""
    try:
        return _real_import_asyncpg()
    except ImportError as exc:
        raise ConfigError(_MISSING_ASYNCPG_MSG) from exc


# ---------------------------------------------------------------------------
# agtype helpers
# ---------------------------------------------------------------------------


def _agtype_to_str(value: Any) -> str:
    """Coerce an AGE ``agtype`` scalar to a plain Python string.

    AGE returns scalar columns as JSON-tagged strings: a string entity
    name comes back as ``"alice"`` (with embedded quotes); the optional
    ``::vertex`` / ``::edge`` suffix is stripped. ``None`` and empty
    inputs collapse to the empty string.
    """
    if value is None or value == "":
        return ""
    raw = str(value)
    # Strip the optional ``::vertex`` / ``::edge`` type suffix that AGE
    # sometimes appends to scalar results (depends on the column type).
    if "::" in raw:
        raw = raw.rsplit("::", 1)[0]
    # If the remaining string is JSON-encoded, decode it; otherwise
    # return verbatim (covers ``plain`` literals from mocks/tests).
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    return str(decoded) if decoded is not None else ""


def _agtype_to_int(value: Any) -> int:
    """Coerce an AGE ``agtype`` scalar to a plain Python int.

    ``None`` and empty inputs collapse to ``0`` — that matches the
    semantics of an uninitialised counter (vertex_count / edge_count
    before any data has landed).
    """
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value
    raw = str(value).strip('"')
    try:
        return int(raw)
    except ValueError:
        return 0


def _agtype_to_str_list(value: Any) -> list[str]:
    """Decode an AGE ``agtype`` array column into a Python list of strings."""
    if value is None or value == "":
        return []
    raw = str(value)
    if "::" in raw:
        raw = raw.rsplit("::", 1)[0]
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if item is not None]


# ---------------------------------------------------------------------------
# Injection guard
# ---------------------------------------------------------------------------


def _validate_rel_type(rel_type: str) -> str:
    """Reject relationship types containing characters that break cypher.

    AGE accepts the openCypher body inside a Postgres dollar-quoted
    string (``$$ ... $$``). Inside that body, backticks and single
    quotes are the two escape vectors that could break out of literal
    contexts; backslashes are rejected for parity with the FalkorDB
    adapter (S-155-F1) so the safety rule is uniform across backends.
    """
    if "`" in rel_type or "'" in rel_type or "\\" in rel_type:
        msg = (
            f"invalid rel_type {rel_type!r}: backticks, single quotes, "
            "and backslashes are not allowed"
        )
        raise ValueError(msg)
    return rel_type


# ---------------------------------------------------------------------------
# Cypher fragments
# ---------------------------------------------------------------------------


def _wrap(cypher: str, returns: str) -> str:
    """Wrap a Cypher fragment in the AGE ``SELECT * FROM cypher(...)`` envelope.

    Each call site builds its own ``returns`` column spec (a string like
    ``"name agtype"`` or ``"src agtype, tgt agtype, rel_type agtype"``)
    because AGE requires the result columns to be typed in SQL.

    Safety: ``_GRAPH_NAME`` is a module-level constant; ``cypher`` is built
    from module-level templates whose only variable substitution is the
    relationship type, which is run through :func:`_validate_rel_type``
    before substitution. ``returns`` is also module-internal. Cypher
    parameters arrive via the ``$1::agtype`` placeholder bound by asyncpg.
    """
    return f"SELECT * FROM cypher('{_GRAPH_NAME}', $$ {cypher} $$, $1::agtype) AS ({returns})"  # noqa: S608  # nosec B608


def _wrap_no_params(cypher: str, returns: str) -> str:
    """Same as :func:`_wrap` but for queries with no Cypher parameters.

    Safety: same justification as :func:`_wrap` — every interpolated
    fragment is a module-internal constant or has been validated.
    """
    return f"SELECT * FROM cypher('{_GRAPH_NAME}', $$ {cypher} $$) AS ({returns})"  # noqa: S608  # nosec B608


_ADD_EDGE_CYPHER_TEMPLATE = (
    "MERGE (s:Entity {{name: $src}}) "
    "MERGE (t:Entity {{name: $tgt}}) "
    "MERGE (s)-[r:`{rel_type}`]->(t) "
    "ON CREATE SET r.first_seen = $ts, r.last_seen = $ts, r.event_count = 1 "
    "ON MATCH SET r.first_seen = CASE WHEN r.first_seen < $ts THEN r.first_seen ELSE $ts END, "
    "             r.last_seen  = CASE WHEN r.last_seen  > $ts THEN r.last_seen  ELSE $ts END, "
    "             r.event_count = coalesce(r.event_count, 0) + 1 "
    "RETURN 1"
)

_LOAD_EDGE_CYPHER_TEMPLATE = (
    "MERGE (s:Entity {{name: $src}}) "
    "MERGE (t:Entity {{name: $tgt}}) "
    "MERGE (s)-[r:`{rel_type}`]->(t) "
    "SET r.first_seen = $first, r.last_seen = $last, r.event_count = $count "
    "RETURN 1"
)

_CLEAR_CYPHER = "MATCH (n) DETACH DELETE n RETURN 1"

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
    """Build the neighbours cypher with optional rel-type filtering."""
    depth = max(1, int(depth))
    if rel_types:
        for rt in rel_types:
            _validate_rel_type(rt)
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


# ---------------------------------------------------------------------------
# Bootstrap SQL (raw — runs outside Cypher envelope)
# ---------------------------------------------------------------------------


_BOOTSTRAP_CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS age"
_BOOTSTRAP_LOAD_AGE = "LOAD 'age'"
_BOOTSTRAP_SET_SEARCH_PATH = 'SET search_path = ag_catalog, "$user", public'
_BOOTSTRAP_GRAPH_EXISTS = "SELECT name FROM ag_catalog.ag_graph WHERE name = $1"
_BOOTSTRAP_CREATE_GRAPH = "SELECT create_graph($1)"


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PostgresAGEGraphBackend:
    """:class:`GraphBackend` adapter over an asyncpg pool with Apache AGE.

    Construct directly with a pre-built asyncpg pool (used by tests), or
    via :meth:`connect` for production wiring.
    """

    __slots__ = ("_edge_count", "_pool", "_vertex_count")

    def __init__(self, *, pool: Any) -> None:
        self._pool = pool
        self._vertex_count = 0
        self._edge_count = 0

    @classmethod
    async def connect(
        cls,
        *,
        url: str,
        min_size: int = 2,
        max_size: int = 10,
        command_timeout: float = 30.0,
    ) -> PostgresAGEGraphBackend:
        """Build an asyncpg pool, run bootstrap, and return a ready adapter.

        The pool's ``setup`` callback runs ``LOAD 'age'`` + ``SET
        search_path`` on every checked-out connection — required because
        AGE state is session-scoped.
        """
        asyncpg_mod = _load_asyncpg()
        backend = cls.__new__(cls)
        backend._pool = None  # populated below
        backend._vertex_count = 0
        backend._edge_count = 0

        pool = await asyncpg_mod.create_pool(
            dsn=url,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
            setup=backend._setup_connection,
        )
        backend._pool = pool
        await backend.bootstrap()
        return backend

    # ------------------------------------------------------------------
    # Pool callback + lifecycle
    # ------------------------------------------------------------------

    async def _setup_connection(self, conn: Any) -> None:
        """Per-connection AGE bootstrap (LOAD + search_path).

        Registered as the asyncpg pool's ``setup`` callback so every
        checked-out connection enters Cypher-ready state. ``LOAD 'age'``
        is session-scoped — without this the ``cypher()`` function is
        not in the schema search path.
        """
        await conn.execute(_BOOTSTRAP_LOAD_AGE)
        await conn.execute(_BOOTSTRAP_SET_SEARCH_PATH)

    async def bootstrap(self) -> None:
        """One-shot bootstrap: install extension + create graph (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_BOOTSTRAP_CREATE_EXTENSION)
            existing = await conn.fetchval(_BOOTSTRAP_GRAPH_EXISTS, _GRAPH_NAME)
            if existing is None:
                await conn.execute(_BOOTSTRAP_CREATE_GRAPH, _GRAPH_NAME)

    async def close(self) -> None:
        """Close the underlying pool; safe to call multiple times."""
        await self._pool.close()

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
        sql = _wrap(cypher, "ok agtype")
        payload = json.dumps({"src": source_id, "tgt": target_id, "ts": timestamp_ns})
        async with self._pool.acquire() as conn:
            await conn.execute(sql, payload)

    async def load(
        self,
        rows: list[tuple[str, str, str, int, int, int]],
    ) -> None:
        """Wipe the graph and bulk-insert ``rows`` (matches :class:`EntityGraph.load`)."""
        async with self._pool.acquire() as conn:
            clear_sql = _wrap_no_params(_CLEAR_CYPHER, "ok agtype")
            await conn.execute(clear_sql)
            for src, tgt, rel_type, first, last, count in rows:
                rel = _validate_rel_type(rel_type)
                cypher = _LOAD_EDGE_CYPHER_TEMPLATE.format(rel_type=rel)
                sql = _wrap(cypher, "ok agtype")
                payload = json.dumps(
                    {
                        "src": src,
                        "tgt": tgt,
                        "first": first,
                        "last": last,
                        "count": count,
                    }
                )
                await conn.execute(sql, payload)

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
        sql = _wrap(cypher, "name agtype")
        payload = json.dumps({"src": entity_id})
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, payload)
        return [{"entity_id": _agtype_to_str(row[0])} for row in rows]

    async def shortest_path(self, source_id: str, target_id: str) -> list[str]:
        sql = _wrap(_SHORTEST_PATH_CYPHER, "path agtype")
        payload = json.dumps({"src": source_id, "tgt": target_id})
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, payload)
        if not rows:
            return []
        first = rows[0][0]
        return _agtype_to_str_list(first)

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]:
        node_sql = _wrap(_subgraph_nodes_cypher(depth), "name agtype")
        node_payload = json.dumps({"src": entity_id})
        async with self._pool.acquire() as conn:
            node_rows = await conn.fetch(node_sql, node_payload)
            nodes: list[str] = [_agtype_to_str(row[0]) for row in node_rows]
            if not nodes:
                return ([], [])
            edge_sql = _wrap(
                _SUBGRAPH_EDGES_CYPHER,
                "src agtype, tgt agtype, rel_type agtype",
            )
            edge_payload = json.dumps({"names": nodes})
            edge_rows = await conn.fetch(edge_sql, edge_payload)
        edges: list[dict[str, str]] = [
            {
                "source_id": _agtype_to_str(row[0]),
                "target_id": _agtype_to_str(row[1]),
                "rel_type": _agtype_to_str(row[2]),
            }
            for row in edge_rows
        ]
        return (nodes, edges)

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]:
        sql = _wrap(_GET_RELATED_CYPHER, "name agtype, rel_type agtype")
        payload = json.dumps({"src": entity_uuid})
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, payload)
        relations: list[EntityRelation] = []
        for row in rows:
            neighbor_id = _agtype_to_str(row[0])
            rel_type = _agtype_to_str(row[1])
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
        sql = _wrap_no_params(
            _EXPORT_EDGES_CYPHER,
            "src agtype, tgt agtype, rel_type agtype, first agtype, last agtype, count agtype",
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [
            (
                _agtype_to_str(row[0]),
                _agtype_to_str(row[1]),
                _agtype_to_str(row[2]),
                _agtype_to_int(row[3]),
                _agtype_to_int(row[4]),
                _agtype_to_int(row[5]),
            )
            for row in rows
        ]

    async def refresh_counts(self) -> None:
        """Update cached ``vertex_count`` / ``edge_count`` from the server."""
        v_sql = _wrap_no_params(_VERTEX_COUNT_CYPHER, "n agtype")
        e_sql = _wrap_no_params(_EDGE_COUNT_CYPHER, "n agtype")
        async with self._pool.acquire() as conn:
            v_val = await conn.fetchval(v_sql)
            e_val = await conn.fetchval(e_sql)
        self._vertex_count = _agtype_to_int(v_val)
        self._edge_count = _agtype_to_int(e_val)

    @property
    def vertex_count(self) -> int:
        return self._vertex_count

    @property
    def edge_count(self) -> int:
        return self._edge_count
