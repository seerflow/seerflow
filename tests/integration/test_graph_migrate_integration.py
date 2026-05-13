"""Docker-gated integration tests for ``seerflow graph migrate`` (S-155-F3).

Exercises the migration handler end-to-end against real persistent
graph backends (FalkorDB, PostgreSQL AGE). Tests are gated behind the
``requires_falkordb`` / ``requires_postgres_age`` markers and skipped
by default so the standard suite stays Docker-free.

Run with::

    pytest -m requires_falkordb tests/integration/test_graph_migrate_integration.py
    pytest -m requires_postgres_age tests/integration/test_graph_migrate_integration.py
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest

from seerflow.config import SeerflowConfig, StorageConfig
from seerflow.graph.backends import InMemoryIgraphBackend

if TYPE_CHECKING:
    from collections.abc import Iterator


_SAMPLE_EDGES: list[tuple[str, str, str, int, int, int]] = [
    ("user:alice", "host:web-01", "logged_into", 100, 500, 3),
    ("user:bob", "host:web-02", "logged_into", 110, 510, 2),
    ("host:web-01", "ip:10.0.0.5", "connected_to", 120, 520, 5),
    ("user:carol", "host:db-01", "sudo_on", 130, 530, 1),
    ("user:dave", "host:web-01", "logged_into", 140, 540, 4),
]


def _make_migrate_args(
    *,
    from_backend: str,
    to_backend: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="graph",
        graph_cmd="migrate",
        from_backend=from_backend,
        to_backend=to_backend,
        batch_size=2,
        dry_run=False,
        wipe_destination=False,
        config=None,
    )


# ---------------------------------------------------------------------------
# FalkorDB target
# ---------------------------------------------------------------------------

pytest.importorskip("falkordb", reason="graph-falkordb extra not installed")
_tc_core = pytest.importorskip("testcontainers.core.container", reason="testcontainers missing")
_DockerContainer = _tc_core.DockerContainer

if TYPE_CHECKING:
    from testcontainers.core.container import DockerContainer as _DockerContainerT


@pytest.fixture(scope="module")
def falkordb_container() -> Iterator[_DockerContainerT]:
    container = _DockerContainer("falkordb/falkordb:latest").with_exposed_ports(6379)
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.mark.requires_falkordb
@pytest.mark.asyncio
async def test_migrate_igraph_to_falkordb(
    falkordb_container: _DockerContainerT,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip: populate igraph, migrate to FalkorDB, verify counts."""
    from seerflow.graph.falkordb_backend import FalkorDBGraphBackend
    from seerflow.graph_migrate_cmd import run_graph_migrate

    host = falkordb_container.get_container_host_ip()
    port = int(falkordb_container.get_exposed_port(6379))
    falkordb_url = f"falkor://{host}:{port}"

    # Pre-populate an in-memory source.
    source_backend = InMemoryIgraphBackend()
    source_backend.inner_graph.load(_SAMPLE_EDGES)

    # Stub the factory: igraph → our pre-loaded source, falkordb → real container.
    async def fake_connect(storage_cfg: StorageConfig) -> object:
        if storage_cfg.graph_backend == "igraph":
            return source_backend
        if storage_cfg.graph_backend == "falkordb":
            return await FalkorDBGraphBackend.connect(url=falkordb_url)
        msg = f"unexpected backend in test: {storage_cfg.graph_backend!r}"
        raise AssertionError(msg)

    def fake_load_config(_path: str | None) -> SeerflowConfig:
        return SeerflowConfig(
            storage=StorageConfig(graph_backend="igraph", falkordb_url=falkordb_url),
        )

    monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", fake_connect)
    monkeypatch.setattr("seerflow.graph_migrate_cmd.load_config", fake_load_config)

    rc = await run_graph_migrate(
        _make_migrate_args(from_backend="igraph", to_backend="falkordb"),
    )
    assert rc == 0

    # Verify destination matches by reconnecting.
    verify = await FalkorDBGraphBackend.connect(url=falkordb_url)
    try:
        exported = await verify.export_edges()
        assert {(e[0], e[1], e[2]) for e in exported} == {
            (e[0], e[1], e[2]) for e in _SAMPLE_EDGES
        }
    finally:
        await verify.close()


# ---------------------------------------------------------------------------
# PostgreSQL AGE target
# ---------------------------------------------------------------------------

pytest.importorskip("asyncpg", reason="graph-postgres-age extra not installed")
_tc_postgres = pytest.importorskip(
    "testcontainers.postgres", reason="testcontainers[postgres] missing"
)
_PostgresContainer = _tc_postgres.PostgresContainer

if TYPE_CHECKING:
    from testcontainers.postgres import PostgresContainer as _PostgresContainerT


@pytest.fixture(scope="module")
def postgres_age_container() -> Iterator[_PostgresContainerT]:
    container = _PostgresContainer(image="apache/age:latest")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.mark.requires_postgres_age
@pytest.mark.asyncio
async def test_migrate_igraph_to_postgres_age(
    postgres_age_container: _PostgresContainerT,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round-trip: populate igraph, migrate to AGE, verify counts."""
    from seerflow.graph.postgres_age_backend import PostgresAGEGraphBackend
    from seerflow.graph_migrate_cmd import run_graph_migrate

    age_url = postgres_age_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )

    source_backend = InMemoryIgraphBackend()
    source_backend.inner_graph.load(_SAMPLE_EDGES)

    async def fake_connect(storage_cfg: StorageConfig) -> object:
        if storage_cfg.graph_backend == "igraph":
            return source_backend
        if storage_cfg.graph_backend == "postgres_age":
            return await PostgresAGEGraphBackend.connect(url=age_url)
        msg = f"unexpected backend in test: {storage_cfg.graph_backend!r}"
        raise AssertionError(msg)

    def fake_load_config(_path: str | None) -> SeerflowConfig:
        return SeerflowConfig(
            storage=StorageConfig(graph_backend="igraph", postgresql_url=age_url),
        )

    monkeypatch.setattr("seerflow.graph_migrate_cmd.connect_graph", fake_connect)
    monkeypatch.setattr("seerflow.graph_migrate_cmd.load_config", fake_load_config)

    rc = await run_graph_migrate(
        _make_migrate_args(from_backend="igraph", to_backend="postgres_age"),
    )
    assert rc == 0

    verify = await PostgresAGEGraphBackend.connect(url=age_url)
    try:
        exported = await verify.export_edges()
        assert {(e[0], e[1], e[2]) for e in exported} == {
            (e[0], e[1], e[2]) for e in _SAMPLE_EDGES
        }
    finally:
        await verify.close()
