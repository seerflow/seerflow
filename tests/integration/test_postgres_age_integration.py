"""Docker-gated integration test for ``PostgresAGEGraphBackend`` (S-155-F2).

Spins a real AGE-enabled Postgres container via testcontainers and runs
an end-to-end round-trip (bootstrap → add → query → export). Deselected
by default; run with::

    pytest -m requires_postgres_age tests/integration/test_postgres_age_integration.py

The default suite never executes this file — both ``asyncpg`` and
``testcontainers`` are optional dependencies, gated behind
``importorskip`` so collection still succeeds on a clean install.

The container image is ``apache/age:latest`` which bundles
PostgreSQL 16 with the AGE extension pre-installed. The adapter still
runs ``CREATE EXTENSION IF NOT EXISTS age`` on connect to confirm the
production-bootstrap path works against this image.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

# Skip collection cleanly when the extras are absent.
pytest.importorskip("asyncpg", reason="graph-postgres-age extra not installed")
testcontainers_postgres = pytest.importorskip(
    "testcontainers.postgres", reason="testcontainers[postgres] not installed"
)
PostgresContainer = testcontainers_postgres.PostgresContainer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from testcontainers.postgres import PostgresContainer as _PostgresContainer

from seerflow.graph.postgres_age_backend import PostgresAGEGraphBackend  # noqa: E402

pytestmark = pytest.mark.requires_postgres_age


@pytest.fixture(scope="module")
def postgres_age_container() -> Iterator[_PostgresContainer]:
    container = PostgresContainer(image="apache/age:latest")
    container.start()
    try:
        yield container
    finally:
        container.stop()


async def test_end_to_end_round_trip(
    postgres_age_container: _PostgresContainer,
) -> None:
    url = postgres_age_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    backend = await PostgresAGEGraphBackend.connect(url=url)
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


async def test_load_export_round_trip(
    postgres_age_container: _PostgresContainer,
) -> None:
    url = postgres_age_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    backend = await PostgresAGEGraphBackend.connect(url=url)
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


async def test_bootstrap_is_idempotent(
    postgres_age_container: _PostgresContainer,
) -> None:
    """Connecting twice in a row must not raise (graph already exists path)."""
    url = postgres_age_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    first = await PostgresAGEGraphBackend.connect(url=url)
    await first.close()
    second = await PostgresAGEGraphBackend.connect(url=url)
    await second.close()
