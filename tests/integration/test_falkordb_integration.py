"""Docker-gated integration test for ``FalkorDBGraphBackend`` (S-155-F1).

Spins a real FalkorDB container via testcontainers and runs an
end-to-end round-trip (add → query → export). Deselected by default;
run with::

    pytest -m requires_falkordb tests/integration/test_falkordb_integration.py

The default suite never executes this file — both the ``falkordb`` client
and the ``testcontainers`` package are optional dependencies, gated behind
``importorskip`` so collection still succeeds on a clean install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# Skip collection cleanly when the extras are absent.
pytest.importorskip("falkordb", reason="falkordb extra not installed")
testcontainers_core = pytest.importorskip(
    "testcontainers.core.container", reason="testcontainers not installed"
)
DockerContainer = testcontainers_core.DockerContainer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from testcontainers.core.container import DockerContainer as _DockerContainer

from seerflow.graph.falkordb_backend import FalkorDBGraphBackend  # noqa: E402

pytestmark = pytest.mark.requires_falkordb


@pytest.fixture(scope="module")
def falkordb_container() -> Iterator[_DockerContainer]:
    container = DockerContainer("falkordb/falkordb:latest").with_exposed_ports(6379)
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.mark.asyncio
async def test_end_to_end_round_trip(falkordb_container: _DockerContainer) -> None:
    host = falkordb_container.get_container_host_ip()
    port = int(falkordb_container.get_exposed_port(6379))
    backend = await FalkorDBGraphBackend.connect(url=f"falkor://{host}:{port}")
    try:
        await backend.add_edge("user:alice", "host:web-01", "logged_into", 1_000)
        await backend.add_edge("host:web-01", "ip:10.0.0.5", "connected_to", 2_000)
        neighbours = await backend.get_neighbors("user:alice", depth=2)
        ids = {n["entity_id"] for n in neighbours}
        assert ids >= {"host:web-01", "ip:10.0.0.5"}
        rows = await backend.export_edges()
        assert len(rows) == 2
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_load_export_round_trip(falkordb_container: _DockerContainer) -> None:
    host = falkordb_container.get_container_host_ip()
    port = int(falkordb_container.get_exposed_port(6379))
    backend = await FalkorDBGraphBackend.connect(url=f"falkor://{host}:{port}")
    try:
        rows: list[tuple[str, str, str, int, int, int]] = [
            ("a", "b", "uses", 1, 5, 3),
            ("b", "c", "uses", 2, 6, 7),
        ]
        await backend.load(rows)
        exported = await backend.export_edges()
        assert sorted(exported) == sorted(rows)
        await backend.refresh_counts()
        assert backend.vertex_count == 3
        assert backend.edge_count == 2
    finally:
        await backend.close()
