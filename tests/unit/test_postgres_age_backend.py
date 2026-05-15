"""Unit tests for ``PostgresAGEGraphBackend`` (S-155-F2).

Uses ``unittest.mock.AsyncMock`` to forge an ``asyncpg`` pool whose
``acquire()`` returns an async-context-manager connection. The mocked
connection captures every ``execute`` / ``fetchval`` / ``fetch`` call so
each test asserts on the Cypher-in-SQL envelope emitted by the adapter.
The Docker-gated round-trip lives in
``tests/integration/test_postgres_age_integration.py`` behind the
``requires_postgres_age`` marker.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.graph.backends import GraphBackend
from seerflow.graph.postgres_age_backend import PostgresAGEGraphBackend


class _Recorder:
    """Records every async call on the mocked asyncpg connection."""

    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        # Programmable return values, popped left-to-right by each helper.
        self.fetchval_returns: list[Any] = []
        self.fetch_returns: list[list[tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.execute_calls.append((sql, args))
        return "OK"

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.fetchval_calls.append((sql, args))
        return self.fetchval_returns.pop(0) if self.fetchval_returns else None

    async def fetch(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        self.fetch_calls.append((sql, args))
        return self.fetch_returns.pop(0) if self.fetch_returns else []


def _fake_pool(recorder: _Recorder) -> MagicMock:
    """Build an asyncpg-style pool whose ``acquire()`` returns ``recorder``."""

    class _Ctx:
        async def __aenter__(self) -> _Recorder:
            return recorder

        async def __aexit__(self, *_exc: Any) -> None:
            return None

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_Ctx())
    pool.close = AsyncMock()
    return pool


def _backend_with(recorder: _Recorder) -> PostgresAGEGraphBackend:
    return PostgresAGEGraphBackend(pool=_fake_pool(recorder))


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_satisfies_graph_backend_protocol() -> None:
    backend = _backend_with(_Recorder())
    assert isinstance(backend, GraphBackend)


# ---------------------------------------------------------------------------
# add_edge
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_add_edge_emits_cypher_in_sql_wrapper() -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    await backend.add_edge("a", "b", "uses", 1_000)
    assert len(rec.execute_calls) == 1
    sql, params = rec.execute_calls[0]
    # Cypher-in-SQL envelope.
    assert "cypher(" in sql
    assert "seerflow_graph" in sql
    assert "MERGE" in sql
    # Single agtype JSON param carrying src/tgt/ts.
    assert len(params) == 1
    payload = params[0]
    assert "a" in payload and "b" in payload and "1000" in payload


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["bad`type", "has'quote", "has\\backslash"])
async def test_add_edge_rejects_unsafe_chars_in_rel_type(bad: str) -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    with pytest.raises(ValueError, match="not allowed"):
        await backend.add_edge("a", "b", bad, 1)
    assert rec.execute_calls == []


# ---------------------------------------------------------------------------
# get_neighbors
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_neighbors_returns_entity_id_dicts() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([('"b"',), ('"c"',)])
    backend = _backend_with(rec)
    out = await backend.get_neighbors("a", depth=2)
    assert out == [{"entity_id": "b"}, {"entity_id": "c"}]
    sql, _params = rec.fetch_calls[0]
    assert "cypher(" in sql and "MATCH" in sql


@pytest.mark.unit
async def test_get_neighbors_returns_empty_when_no_rows() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([])
    backend = _backend_with(rec)
    assert await backend.get_neighbors("missing", depth=1) == []


@pytest.mark.unit
async def test_get_neighbors_filters_by_rel_types() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([])
    backend = _backend_with(rec)
    await backend.get_neighbors("a", rel_types=("uses", "owns"), depth=1)
    sql, _params = rec.fetch_calls[0]
    assert "uses" in sql and "owns" in sql
    assert "type(" in sql


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["ba`d", "ba'd", "ba\\d"])
async def test_get_neighbors_rejects_unsafe_chars_in_rel_types(bad: str) -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    with pytest.raises(ValueError, match="not allowed"):
        await backend.get_neighbors("a", rel_types=("good", bad))


# ---------------------------------------------------------------------------
# shortest_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_shortest_path_returns_list_of_ids() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([('["a", "b", "c"]',)])
    backend = _backend_with(rec)
    assert await backend.shortest_path("a", "c") == ["a", "b", "c"]


@pytest.mark.unit
async def test_shortest_path_returns_empty_when_no_path() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([])
    backend = _backend_with(rec)
    assert await backend.shortest_path("a", "z") == []


@pytest.mark.unit
async def test_shortest_path_returns_empty_when_first_row_is_null() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([(None,)])
    backend = _backend_with(rec)
    assert await backend.shortest_path("a", "z") == []


# ---------------------------------------------------------------------------
# get_subgraph
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_subgraph_returns_nodes_and_edges() -> None:
    rec = _Recorder()
    # First fetch: nodes; second: edges.
    rec.fetch_returns.append([('"a"',), ('"b"',), ('"c"',)])
    rec.fetch_returns.append([('"a"', '"b"', '"uses"'), ('"b"', '"c"', '"uses"')])
    backend = _backend_with(rec)
    nodes, edges = await backend.get_subgraph("a", depth=2)
    assert set(nodes) == {"a", "b", "c"}
    assert {"source_id": "a", "target_id": "b", "rel_type": "uses"} in edges
    assert {"source_id": "b", "target_id": "c", "rel_type": "uses"} in edges


@pytest.mark.unit
async def test_get_subgraph_empty_when_seed_unknown() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([])
    backend = _backend_with(rec)
    nodes, edges = await backend.get_subgraph("missing", depth=2)
    assert nodes == []
    assert edges == []


# ---------------------------------------------------------------------------
# get_related
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_related_returns_entity_relations() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([('"b"', '"uses"'), ('"c"', '"owns"')])
    backend = _backend_with(rec)
    rels = await backend.get_related("a")
    assert {r.entity_uuid for r in rels} == {"b", "c"}
    assert {r.relation_type for r in rels} == {"uses", "owns"}


@pytest.mark.unit
async def test_get_related_skips_empty_relation_types() -> None:
    rec = _Recorder()
    rec.fetch_returns.append([('"b"', '""'), ('"c"', '"owns"')])
    backend = _backend_with(rec)
    rels = await backend.get_related("a")
    assert [r.entity_uuid for r in rels] == ["c"]


# ---------------------------------------------------------------------------
# load / export
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_load_clears_then_bulk_inserts() -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    rows: list[tuple[str, str, str, int, int, int]] = [
        ("a", "b", "uses", 1, 5, 3),
        ("b", "c", "uses", 2, 6, 7),
    ]
    await backend.load(rows)
    # First execute = clear; subsequent = per-row inserts.
    assert "DELETE" in rec.execute_calls[0][0]
    assert len(rec.execute_calls) == 1 + len(rows)
    # The second call params should carry the first row's payload.
    second_sql, second_args = rec.execute_calls[1]
    assert "MERGE" in second_sql
    assert "a" in second_args[0] and "b" in second_args[0]


@pytest.mark.unit
async def test_load_no_rows_only_clears() -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    await backend.load([])
    assert len(rec.execute_calls) == 1
    assert "DELETE" in rec.execute_calls[0][0]


@pytest.mark.unit
async def test_load_rejects_unsafe_chars_in_rel_type() -> None:
    rec = _Recorder()
    backend = _backend_with(rec)
    with pytest.raises(ValueError, match="not allowed"):
        await backend.load([("a", "b", "bad'rel", 1, 5, 1)])


@pytest.mark.unit
async def test_export_edges_returns_storage_tuples() -> None:
    rec = _Recorder()
    rec.fetch_returns.append(
        [
            ('"a"', '"b"', '"uses"', "1", "5", "3"),
            ('"b"', '"c"', '"uses"', "2", "6", "7"),
        ]
    )
    backend = _backend_with(rec)
    rows = await backend.export_edges()
    assert rows == [
        ("a", "b", "uses", 1, 5, 3),
        ("b", "c", "uses", 2, 6, 7),
    ]


# ---------------------------------------------------------------------------
# vertex_count / edge_count + refresh
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_refresh_counts_pulls_from_server() -> None:
    rec = _Recorder()
    rec.fetchval_returns.extend(["7", "12"])
    backend = _backend_with(rec)
    assert backend.vertex_count == 0
    assert backend.edge_count == 0
    await backend.refresh_counts()
    assert backend.vertex_count == 7
    assert backend.edge_count == 12


@pytest.mark.unit
async def test_refresh_counts_handles_none_returns() -> None:
    rec = _Recorder()
    rec.fetchval_returns.extend([None, None])
    backend = _backend_with(rec)
    await backend.refresh_counts()
    assert backend.vertex_count == 0
    assert backend.edge_count == 0


# ---------------------------------------------------------------------------
# Lifecycle / connect / bootstrap
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_close_calls_pool_close() -> None:
    rec = _Recorder()
    pool = _fake_pool(rec)
    backend = PostgresAGEGraphBackend(pool=pool)
    await backend.close()
    pool.close.assert_awaited_once()


@pytest.mark.unit
async def test_bootstrap_runs_create_extension_and_create_graph() -> None:
    rec = _Recorder()
    rec.fetchval_returns.append(None)  # ag_graph lookup -> not present
    backend = _backend_with(rec)
    await backend.bootstrap()
    sql_blob = " ".join(call[0] for call in rec.execute_calls)
    assert "CREATE EXTENSION IF NOT EXISTS age" in sql_blob
    assert any("create_graph" in c[0] for c in rec.execute_calls)
    # Lookup query first, then create_graph.
    assert "ag_graph" in rec.fetchval_calls[0][0]


@pytest.mark.unit
async def test_bootstrap_skips_create_graph_when_already_present() -> None:
    rec = _Recorder()
    rec.fetchval_returns.append("seerflow_graph")  # graph already exists
    backend = _backend_with(rec)
    await backend.bootstrap()
    # CREATE EXTENSION still runs, but create_graph should NOT.
    assert any("CREATE EXTENSION" in c[0] for c in rec.execute_calls)
    assert not any("create_graph" in c[0] for c in rec.execute_calls)


@pytest.mark.unit
async def test_connect_class_method_builds_pool_and_bootstraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``connect`` lazy-imports asyncpg, builds a pool, and runs bootstrap."""
    rec = _Recorder()
    rec.fetchval_returns.append(None)
    captured: dict[str, Any] = {}

    async def fake_create_pool(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_pool(rec)

    class _FakeAsyncpg:
        create_pool = staticmethod(fake_create_pool)

    import seerflow.graph.postgres_age_backend as mod

    monkeypatch.setattr(mod, "_load_asyncpg", lambda: _FakeAsyncpg)
    backend = await PostgresAGEGraphBackend.connect(
        url="postgresql://u:p@h/db",
        min_size=1,
        max_size=4,
        command_timeout=5.0,
    )
    assert isinstance(backend, PostgresAGEGraphBackend)
    assert captured["dsn"] == "postgresql://u:p@h/db"
    assert captured["min_size"] == 1
    assert captured["max_size"] == 4
    assert captured["command_timeout"] == 5.0
    # Bootstrap should have run at least one execute (CREATE EXTENSION).
    assert any("CREATE EXTENSION" in c[0] for c in rec.execute_calls)


@pytest.mark.unit
async def test_setup_connection_loads_age_and_sets_search_path() -> None:
    """The pool setup callback runs LOAD 'age' + SET search_path on each connection."""
    rec = _Recorder()
    backend = _backend_with(rec)
    await backend._setup_connection(rec)
    sql_blob = " ".join(call[0] for call in rec.execute_calls)
    assert "LOAD 'age'" in sql_blob
    assert "search_path" in sql_blob
    assert "ag_catalog" in sql_blob


# ---------------------------------------------------------------------------
# Lazy import
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_asyncpg_raises_config_error_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the asyncpg import fails, ``_load_asyncpg`` surfaces a ``ConfigError``."""
    import seerflow.graph.postgres_age_backend as mod
    from seerflow.config import ConfigError

    def _raise_import() -> Any:
        raise ImportError("No module named 'asyncpg'")

    monkeypatch.setattr(mod, "_real_import_asyncpg", _raise_import)
    with pytest.raises(ConfigError, match="graph-postgres-age"):
        mod._load_asyncpg()


@pytest.mark.unit
def test_load_asyncpg_returns_real_module_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: ``_load_asyncpg`` returns whatever ``_real_import_asyncpg`` yields."""
    import seerflow.graph.postgres_age_backend as mod

    sentinel = object()
    monkeypatch.setattr(mod, "_real_import_asyncpg", lambda: sentinel)
    assert mod._load_asyncpg() is sentinel


# ---------------------------------------------------------------------------
# agtype helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"hello"', "hello"),
        ("plain", "plain"),
        ('"with::vertex"::vertex', "with::vertex"),
        ("", ""),
        (None, ""),
    ],
)
def test_agtype_to_str(raw: Any, expected: str) -> None:
    from seerflow.graph.postgres_age_backend import _agtype_to_str

    assert _agtype_to_str(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        (42, 42),
        ('"42"', 42),
        (None, 0),
        ("", 0),
        ("not-a-number", 0),  # ValueError branch
    ],
)
def test_agtype_to_int(raw: Any, expected: int) -> None:
    from seerflow.graph.postgres_age_backend import _agtype_to_int

    assert _agtype_to_int(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('["a", "b", "c"]', ["a", "b", "c"]),
        ('["a", "b", "c"]::list', ["a", "b", "c"]),
        (None, []),
        ("", []),
        ("not-json", []),  # JSON decode error branch
        ('"not-a-list"', []),  # decoded but not a list branch
        ('["a", null, "c"]', ["a", "c"]),  # None filter branch
    ],
)
def test_agtype_to_str_list(raw: Any, expected: list[str]) -> None:
    from seerflow.graph.postgres_age_backend import _agtype_to_str_list

    assert _agtype_to_str_list(raw) == expected
