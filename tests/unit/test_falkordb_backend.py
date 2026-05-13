"""Unit tests for ``FalkorDBGraphBackend`` (S-155-F1).

Uses ``unittest.mock.AsyncMock`` to forge a falkordb client so the tests
run on every CI invocation without Docker. The Docker-gated round-trip
lives in ``tests/integration/test_falkordb_integration.py`` behind the
``requires_falkordb`` marker.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.graph.backends import GraphBackend
from seerflow.graph.falkordb_backend import FalkorDBGraphBackend


def _fake_result(rows: list[list[Any]] | None = None) -> SimpleNamespace:
    """Return an object that mimics ``falkordb.query_result.QueryResult``."""
    return SimpleNamespace(result_set=rows or [])


def _fake_client(graph_query: AsyncMock) -> MagicMock:
    """Build a ``FalkorDB``-like client whose ``select_graph`` returns a graph
    whose ``query`` is the supplied ``AsyncMock``.
    """
    fake_graph = MagicMock()
    fake_graph.query = graph_query
    fake_client = MagicMock()
    fake_client.select_graph = MagicMock(return_value=fake_graph)
    fake_client.aclose = AsyncMock()
    return fake_client


@pytest.mark.unit
def test_satisfies_graph_backend_protocol() -> None:
    backend = FalkorDBGraphBackend(client=_fake_client(AsyncMock()))
    assert isinstance(backend, GraphBackend)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_edge_runs_merge_query() -> None:
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    await backend.add_edge("a", "b", "uses", 1_000)
    call = query.await_args
    assert call is not None
    cypher: str = call.args[0]
    params: dict[str, Any] = call.kwargs["params"]
    assert "MERGE" in cypher
    assert params == {"src": "a", "tgt": "b", "ts": 1_000}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_returns_entity_id_dicts() -> None:
    query = AsyncMock(return_value=_fake_result([["b"], ["c"]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    out = await backend.get_neighbors("a", depth=2)
    assert out == [{"entity_id": "b"}, {"entity_id": "c"}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_returns_empty_when_no_rows() -> None:
    query = AsyncMock(return_value=_fake_result([]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    out = await backend.get_neighbors("missing", depth=1)
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_filters_by_rel_types() -> None:
    query = AsyncMock(return_value=_fake_result([]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    await backend.get_neighbors("a", rel_types=("uses", "owns"), depth=1)
    cypher: str = query.await_args.args[0]
    assert "uses" in cypher and "owns" in cypher
    # Either ``type(r)`` (single-hop) or ``type(rel)`` inside a list
    # comprehension (multi-hop) — both are valid; we just need to assert
    # the cypher actually constrains on relationship type.
    assert "type(" in cypher


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shortest_path_returns_list_of_ids() -> None:
    query = AsyncMock(return_value=_fake_result([[["a", "b", "c"]]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    assert await backend.shortest_path("a", "c") == ["a", "b", "c"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shortest_path_returns_empty_when_no_path() -> None:
    query = AsyncMock(return_value=_fake_result([]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    assert await backend.shortest_path("a", "z") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_subgraph_returns_nodes_and_edges() -> None:
    # First query returns nodes (incl. seed), second returns edges.
    query = AsyncMock(
        side_effect=[
            _fake_result([["a"], ["b"], ["c"]]),
            _fake_result([["a", "b", "uses"], ["b", "c", "uses"]]),
        ]
    )
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    nodes, edges = await backend.get_subgraph("a", depth=2)
    assert set(nodes) == {"a", "b", "c"}
    assert {"source_id": "a", "target_id": "b", "rel_type": "uses"} in edges
    assert {"source_id": "b", "target_id": "c", "rel_type": "uses"} in edges


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_related_returns_entity_relations() -> None:
    query = AsyncMock(return_value=_fake_result([["b", "uses"], ["c", "owns"]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    rels = await backend.get_related("a")
    assert {r.entity_uuid for r in rels} == {"b", "c"}
    assert {r.relation_type for r in rels} == {"uses", "owns"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_related_skips_empty_relation_types() -> None:
    """Defensive: a missing rel_type column is filtered out."""
    query = AsyncMock(return_value=_fake_result([["b", ""], ["c", "owns"]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    rels = await backend.get_related("a")
    assert [r.entity_uuid for r in rels] == ["c"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_clears_then_bulk_inserts() -> None:
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    rows: list[tuple[str, str, str, int, int, int]] = [
        ("a", "b", "uses", 1, 5, 3),
        ("b", "c", "uses", 2, 6, 7),
    ]
    await backend.load(rows)
    first_cypher: str = query.await_args_list[0].args[0]
    assert "DELETE" in first_cypher
    # One DELETE + one insert per row.
    assert query.await_count == 1 + len(rows)
    # The second call params should carry the first row.
    second_params = query.await_args_list[1].kwargs["params"]
    assert second_params == {
        "src": "a",
        "tgt": "b",
        "first": 1,
        "last": 5,
        "count": 3,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_no_rows_only_clears() -> None:
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    await backend.load([])
    assert query.await_count == 1
    assert "DELETE" in query.await_args_list[0].args[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_export_edges_returns_storage_tuples() -> None:
    query = AsyncMock(
        return_value=_fake_result([["a", "b", "uses", 1, 5, 3], ["b", "c", "uses", 2, 6, 7]])
    )
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    rows = await backend.export_edges()
    assert rows == [
        ("a", "b", "uses", 1, 5, 3),
        ("b", "c", "uses", 2, 6, 7),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vertex_and_edge_counts_refresh_from_server() -> None:
    query = AsyncMock(side_effect=[_fake_result([[7]]), _fake_result([[12]])])
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    assert backend.vertex_count == 0
    assert backend.edge_count == 0
    await backend.refresh_counts()
    assert backend.vertex_count == 7
    assert backend.edge_count == 12


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_counts_handles_empty_result_set() -> None:
    query = AsyncMock(side_effect=[_fake_result([]), _fake_result([])])
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    await backend.refresh_counts()
    assert backend.vertex_count == 0
    assert backend.edge_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_calls_client_aclose() -> None:
    client = _fake_client(AsyncMock())
    backend = FalkorDBGraphBackend(client=client)
    await backend.close()
    client.aclose.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_class_method_builds_client_from_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class _FakeFalkor:
        @classmethod
        def from_url(cls, url: str) -> _FakeFalkor:
            captured["url"] = url
            return cls()

        def select_graph(self, name: str) -> Any:
            graph = MagicMock()
            graph.query = AsyncMock(return_value=_fake_result())
            return graph

        async def aclose(self) -> None:
            return None

    import seerflow.graph.falkordb_backend as mod

    monkeypatch.setattr(mod, "_load_falkordb", lambda: _FakeFalkor)
    backend = await FalkorDBGraphBackend.connect(url="falkor://h:6379")
    assert captured["url"] == "falkor://h:6379"
    assert isinstance(backend, FalkorDBGraphBackend)


@pytest.mark.unit
def test_load_falkordb_raises_config_error_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the falkordb import fails, ``_load_falkordb`` surfaces a ``ConfigError``."""
    import seerflow.graph.falkordb_backend as mod
    from seerflow.config import ConfigError

    def _raise_import() -> Any:
        raise ImportError("No module named 'falkordb'")

    monkeypatch.setattr(mod, "_real_import_falkordb", _raise_import)
    with pytest.raises(ConfigError, match="graph-falkordb"):
        mod._load_falkordb()


@pytest.mark.unit
def test_load_falkordb_returns_real_class_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: ``_load_falkordb`` returns whatever ``_real_import_falkordb`` yields."""
    import seerflow.graph.falkordb_backend as mod

    sentinel = object()
    monkeypatch.setattr(mod, "_real_import_falkordb", lambda: sentinel)
    assert mod._load_falkordb() is sentinel


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_edge_rejects_backtick_in_rel_type() -> None:
    """Cypher-injection guard: backticks in ``rel_type`` are rejected."""
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    with pytest.raises(ValueError, match="backticks"):
        await backend.add_edge("a", "b", "bad`type", 1)
    query.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_rejects_backtick_in_rel_type() -> None:
    """Same guard applies to bulk-load rows."""
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    with pytest.raises(ValueError, match="backticks"):
        await backend.load([("a", "b", "bad`rel", 1, 5, 1)])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_neighbors_rejects_backtick_in_rel_types() -> None:
    query = AsyncMock(return_value=_fake_result())
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    with pytest.raises(ValueError, match="backticks"):
        await backend.get_neighbors("a", rel_types=("good", "ba`d"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shortest_path_returns_empty_when_first_row_empty() -> None:
    """The path column is None / empty — fall back to ``[]``."""
    query = AsyncMock(return_value=_fake_result([[None]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    assert await backend.shortest_path("a", "z") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shortest_path_returns_empty_when_first_row_is_falsy_list() -> None:
    """Falsy outer row (``[]``) → empty path."""
    query = AsyncMock(return_value=_fake_result([[]]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    assert await backend.shortest_path("a", "z") == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_subgraph_returns_empty_when_seed_unknown() -> None:
    """Seed not in the graph → first query has no rows → both lists empty."""
    query = AsyncMock(return_value=_fake_result([]))
    backend = FalkorDBGraphBackend(client=_fake_client(query))
    nodes, edges = await backend.get_subgraph("missing", depth=2)
    assert nodes == []
    assert edges == []
