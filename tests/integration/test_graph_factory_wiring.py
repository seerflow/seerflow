"""Integration regression — pipeline → factory-built graph backend (S-155 Task 5).

These tests exercise the same call path the pipeline uses (config →
factory → backend) end-to-end against the default in-memory backend.
They are the regression guard that protects against later changes to
the wiring breaking the foundation.
"""

from __future__ import annotations

import pytest

from seerflow.config import StorageConfig
from seerflow.graph.factory import connect_graph

pytestmark = pytest.mark.integration


async def test_factory_built_backend_round_trips_edges() -> None:
    cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
    backend = await connect_graph(cfg)
    await backend.add_edge("user:alice", "host:web-01", "logged_into", 1_000)
    await backend.add_edge("host:web-01", "ip:10.0.0.5", "connected_to", 2_000)
    neighbours = await backend.get_neighbors("user:alice", depth=2)
    entity_ids = sorted(n["entity_id"] for n in neighbours)
    assert entity_ids == ["host:web-01", "ip:10.0.0.5"]
    rows = await backend.export_edges()
    assert len(rows) == 2


async def test_factory_built_backend_load_rebuilds_graph() -> None:
    cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
    backend = await connect_graph(cfg)
    rows = [
        ("a", "b", "uses", 1, 5, 3),
        ("b", "c", "uses", 2, 6, 7),
    ]
    await backend.load(rows)
    assert backend.edge_count == 2
    assert (await backend.export_edges()) == rows


async def test_factory_built_backend_supports_shortest_path() -> None:
    cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
    backend = await connect_graph(cfg)
    await backend.add_edge("a", "b", "x", 1)
    await backend.add_edge("b", "c", "x", 2)
    path = await backend.shortest_path("a", "c")
    assert path == ["a", "b", "c"]


async def test_factory_built_backend_returns_subgraph() -> None:
    cfg = StorageConfig(backend="sqlite", graph_backend="igraph")
    backend = await connect_graph(cfg)
    await backend.add_edge("a", "b", "x", 1)
    await backend.add_edge("b", "c", "x", 2)
    await backend.add_edge("c", "d", "x", 3)
    nodes, edges = await backend.get_subgraph("a", depth=2)
    assert set(nodes) >= {"a", "b", "c"}
    assert any(e["source_id"] == "a" and e["target_id"] == "b" for e in edges)
