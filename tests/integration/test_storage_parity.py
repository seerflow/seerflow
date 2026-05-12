"""S-074 cross-backend parity suite.

The Seerflow storage layer offers two backends behind the same Protocol
contract: :class:`seerflow.storage.sqlite.SqliteBackend` (default,
zero-config) and :class:`seerflow.storage.postgres.PostgresBackend`
(production scale). The Protocol contract is supposed to make backend
choice an operator-visible knob and an application-code invariant.

This module exercises the same handful of end-to-end scenarios against
both backends to prove that invariant. The SQLite parameter runs on every
``pytest`` invocation; the PostgreSQL parameter is gated by
``@pytest.mark.docker`` and skips when ``testcontainers`` is unavailable.

When adding a new parity scenario:

1. Write the test body as ``async def test_..._round_trip(self, storage)``
   — use the ``storage`` fixture, never reach for ``SqliteBackend`` or
   ``PostgresBackend`` directly.
2. Keep assertions on the Protocol surface (``LogStore``,
   ``AlertStore``, etc.); backend-specific behaviour goes in
   ``test_postgres_integration.py`` or ``test_sqlite_integration.py``.
3. Avoid hard-coded SQL — the whole point of the parity layer is that
   the backends speak different dialects but identical Protocols.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.storage.protocols import (
    AlertStore,
    EntityStore,
    LogStore,
    ModelStore,
)
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

# Lazy import: testcontainers / asyncpg may not be installed. We still want
# the SQLite parameter to run when only the SQLite extras are present.
try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    _HAS_TESTCONTAINERS = True
except ImportError:  # pragma: no cover - tested by skip behaviour
    PostgresContainer = None  # type: ignore[assignment,misc]
    _HAS_TESTCONTAINERS = False


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_postgres_integration.py)
# ---------------------------------------------------------------------------


def _make_event(
    *,
    message: str = "hello",
    severity: int = SeverityLevel.WARNING,
    source_type: str = "syslog",
    template_id: int = -1,
    entity_refs: tuple[str, ...] = (),
    timestamp_ns: int = 1_000_000_000,
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=timestamp_ns,
        observed_ns=timestamp_ns,
        severity_id=SeverityLevel(severity),
        source_type=source_type,
        source_id="src-1",
        template_id=template_id,
        message=message,
        entity_refs=entity_refs,
    )


def _make_alert(
    *,
    alert_id: str | None = None,
    dedup_key: str = "dk-1",
    timestamp_ns: int = 1_000_000_000,
    rule_name: str = "rule",
    severity: int = SeverityLevel.WARNING,
    tactics: tuple[str, ...] = (),
    techniques: tuple[str, ...] = (),
) -> Alert:
    return Alert(
        alert_id=alert_id or str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=timestamp_ns,
        severity_id=SeverityLevel(severity),
        rule_name=rule_name,
        description="d",
        entity_uuid="ent-1",
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(),
        dedup_key=dedup_key,
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


def _to_asyncpg_dsn(dsn: str) -> str:
    """Convert ``psycopg2://`` / ``postgresql+psycopg2://`` DSN to asyncpg form."""
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://", "psycopg2://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix) :]
    return dsn


# ---------------------------------------------------------------------------
# Fixtures — parametrised over the two backends
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _parity_pg_container():  # type: ignore[no-untyped-def]
    """Module-scoped Postgres container — one ``docker run`` for the whole class."""
    if not _HAS_TESTCONTAINERS:
        pytest.skip("testcontainers not installed (docker-gated parity test)")
    with PostgresContainer("postgres:16-alpine") as container:  # type: ignore[misc]
        yield container


@pytest.fixture(
    params=[
        pytest.param("sqlite", id="sqlite"),
        pytest.param("postgresql", id="postgresql", marks=pytest.mark.docker),
    ]
)
async def storage(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[LogStore]:
    """Yield a connected backend instance, fresh per test.

    SQLite path: per-test file under ``tmp_path``.
    PostgreSQL path: per-test logical database carved out of the module-scoped
    container so concurrent tests cannot trample each other.
    """
    backend_kind: str = request.param

    if backend_kind == "sqlite":
        cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "parity.db"))
        sqlite_backend = await SqliteBackend.connect(cfg)
        try:
            yield sqlite_backend
        finally:
            await sqlite_backend.close()
        return

    # PostgreSQL branch — only reached under @pytest.mark.docker.
    import asyncpg  # local import — keeps SQLite-only runs free of asyncpg dep

    from seerflow.storage.postgres import PostgresBackend

    container = request.getfixturevalue("_parity_pg_container")
    base_dsn = _to_asyncpg_dsn(container.get_connection_url())
    db_name = f"parity_{uuid.uuid4().hex[:12]}"

    admin_conn = await asyncpg.connect(dsn=base_dsn)
    try:
        await admin_conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin_conn.close()

    base, _, _ = base_dsn.rpartition("/")
    test_dsn = f"{base}/{db_name}"
    pg_cfg = StorageConfig(backend="postgresql", postgresql_url=test_dsn)
    pg_backend = await PostgresBackend.connect(pg_cfg)
    try:
        yield pg_backend
    finally:
        await pg_backend.close()
        admin_conn = await asyncpg.connect(dsn=base_dsn)
        try:
            await admin_conn.execute(f'DROP DATABASE "{db_name}"')
        finally:
            await admin_conn.close()


# ---------------------------------------------------------------------------
# Parity scenarios
# ---------------------------------------------------------------------------


class TestStorageParity:
    """Each test runs once per backend and must pass on both."""

    async def test_protocol_contract_satisfied(self, storage: LogStore) -> None:
        """Both backends satisfy the full set of storage Protocols."""
        assert isinstance(storage, LogStore)
        assert isinstance(storage, AlertStore)
        assert isinstance(storage, ModelStore)
        assert isinstance(storage, EntityStore)

    async def test_event_write_query_round_trip(self, storage: LogStore) -> None:
        """``write_events`` then ``query_events`` returns rows newest-first."""
        events = [
            _make_event(message="oldest", timestamp_ns=1_000_000_000),
            _make_event(message="middle", timestamp_ns=2_000_000_000),
            _make_event(message="newest", timestamp_ns=3_000_000_000),
        ]
        await storage.write_events(events)
        await storage.flush()

        page = await storage.query_events(EventQuery())
        assert page.total == 3
        # Newest-first ordering is part of the LogStore contract.
        assert page.items[0].message == "newest"
        assert page.items[-1].message == "oldest"

    async def test_event_fts_search(self, storage: LogStore) -> None:
        """``search_text`` matches a known phrase on both backends."""
        await storage.write_events(
            [
                _make_event(message="user admin logged in", timestamp_ns=1_000_000_000),
                _make_event(message="server starting up", timestamp_ns=2_000_000_000),
                _make_event(message="background flush", timestamp_ns=3_000_000_000),
            ]
        )
        await storage.flush()
        results = await storage.search_text("admin", limit=10)
        assert len(results) == 1
        assert "admin" in results[0].message

    async def test_alert_dedup_window(self, storage: AlertStore) -> None:
        """A write inside the dedup window does not produce a new row."""
        window_ns = 10_000_000_000  # 10 s
        a1 = _make_alert(dedup_key="parity-dedup", timestamp_ns=1_000_000_000)
        a2 = _make_alert(dedup_key="parity-dedup", timestamp_ns=1_000_001_000)
        first = await storage.write_alert(a1, dedup_window_ns=window_ns)
        second = await storage.write_alert(a2, dedup_window_ns=window_ns)

        assert first is True
        assert second is False

        page = await storage.query_alerts(AlertQuery())
        assert page.total == 1
        assert page.items[0].dedup_count == 2

    async def test_mitre_junction_filter(self, storage: AlertStore) -> None:
        """``query_alerts(tactic=...)`` drives off the junction table."""
        await storage.write_alert(_make_alert(dedup_key="parity-j1", tactics=("execution",)))
        await storage.write_alert(_make_alert(dedup_key="parity-j2", tactics=("defense-evasion",)))
        page = await storage.query_alerts(AlertQuery(tactic="execution"))
        assert page.total == 1
        assert page.items[0].dedup_key == "parity-j1"

    async def test_model_state_kv_round_trip(self, storage: ModelStore) -> None:
        """``save_state`` → ``load_state`` round-trip + upsert + delete."""
        key = "parity:hst:host:web-01"

        # Initially absent.
        assert await storage.load_state(key) is None

        # Save + reload.
        await storage.save_state(key, b"\x01\x02\x03")
        assert await storage.load_state(key) == b"\x01\x02\x03"

        # Upsert (second save overwrites).
        await storage.save_state(key, b"\xff")
        assert await storage.load_state(key) == b"\xff"

        # Delete clears.
        await storage.delete_state(key)
        assert await storage.load_state(key) is None
