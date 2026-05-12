"""Docker-gated integration tests for the PostgreSQL storage backend (S-073).

These tests spin up a real PostgreSQL container via ``testcontainers`` and
run end-to-end scenarios against :class:`seerflow.storage.postgres.PostgresBackend`.

Marked ``@pytest.mark.docker`` and deselected by default — run with
``pytest -m docker tests/integration/test_postgres_integration.py``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.storage.postgres import PostgresBackend
from seerflow.storage.protocols import (
    AlertStore,
    EntityStore,
    LogStore,
    ModelStore,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.docker


def _to_asyncpg_dsn(dsn: str) -> str:
    """Convert ``psycopg2://`` / ``postgresql+psycopg2://`` DSN to asyncpg form."""
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://", "psycopg2://"):
        if dsn.startswith(prefix):
            return "postgresql://" + dsn[len(prefix) :]
    return dsn


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    """Module-scoped container — one ``docker run`` per test module."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def pg_backend(
    pg_container: PostgresContainer,
) -> AsyncIterator[PostgresBackend]:
    """Function-scoped backend on a fresh ephemeral schema per test."""
    import asyncpg

    dsn = _to_asyncpg_dsn(pg_container.get_connection_url())
    # Each test gets its own logical database derived from the test name
    # so concurrent tests cannot trample each other's tables.
    db_name = f"sf_{uuid4().hex[:12]}"
    admin_conn = await asyncpg.connect(dsn=dsn)
    try:
        await admin_conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin_conn.close()

    # Swap the database name in the DSN.
    base, _, _ = dsn.rpartition("/")
    test_dsn = f"{base}/{db_name}"

    config = StorageConfig(backend="postgresql", postgresql_url=test_dsn)
    backend = await PostgresBackend.connect(config)
    try:
        yield backend
    finally:
        await backend.close()
        admin_conn = await asyncpg.connect(dsn=dsn)
        try:
            await admin_conn.execute(f'DROP DATABASE "{db_name}"')
        finally:
            await admin_conn.close()


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


class TestSchemaBootstrap:
    async def test_isinstance_log_store(self, pg_backend: PostgresBackend) -> None:
        assert isinstance(pg_backend, LogStore)

    async def test_isinstance_alert_store(self, pg_backend: PostgresBackend) -> None:
        assert isinstance(pg_backend, AlertStore)

    async def test_isinstance_model_store(self, pg_backend: PostgresBackend) -> None:
        assert isinstance(pg_backend, ModelStore)

    async def test_isinstance_entity_store(self, pg_backend: PostgresBackend) -> None:
        assert isinstance(pg_backend, EntityStore)

    async def test_graph_store_surface_present(self, pg_backend: PostgresBackend) -> None:
        # ``SqliteBackend`` implements the same minimum GraphStore subset
        # (``write_edge`` + ``load_edges``); ``get_neighbors`` /
        # ``shortest_path`` / ``get_subgraph`` route through the in-memory
        # ``EntityGraph`` rather than the storage layer (architecture
        # decision documented on the Protocol). Match parity here.
        assert hasattr(pg_backend, "write_edge")
        assert hasattr(pg_backend, "load_edges")

    async def test_tables_created(self, pg_backend: PostgresBackend) -> None:
        async with pg_backend._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        table_names = {row["table_name"] for row in rows}
        expected = {
            "events",
            "entity_events",
            "alerts",
            "model_state",
            "templates",
            "graph_edges",
            "alert_tactics",
            "alert_techniques",
            "alert_feedback_events",
            "sigma_rule_state",
            "schema_version",
        }
        missing = expected - table_names
        assert not missing, f"missing tables: {missing}"

    async def test_fts_index_present(self, pg_backend: PostgresBackend) -> None:
        async with pg_backend._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT indexdef FROM pg_indexes WHERE indexname = $1",
                "idx_events_message_fts",
            )
        assert row is not None
        assert "gin" in row["indexdef"].lower()


class TestEvents:
    async def test_write_and_query(self, pg_backend: PostgresBackend) -> None:
        e1 = _make_event(message="login failed for admin", timestamp_ns=2_000_000_000)
        e2 = _make_event(message="server started", timestamp_ns=1_000_000_000)
        await pg_backend.write_events([e1, e2])
        await pg_backend.flush()

        page = await pg_backend.query_events(EventQuery())
        assert page.total == 2
        assert len(page.items) == 2
        # newest first
        assert page.items[0].message == "login failed for admin"

    async def test_query_by_severity_min(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_events(
            [
                _make_event(severity=SeverityLevel.INFORMATIONAL, timestamp_ns=10),
                _make_event(severity=SeverityLevel.ERROR, timestamp_ns=20),
            ]
        )
        await pg_backend.flush()
        page = await pg_backend.query_events(EventQuery(severity_min=SeverityLevel.ERROR))
        assert page.total == 1

    async def test_query_with_entity_join(self, pg_backend: PostgresBackend) -> None:
        ent = str(uuid.uuid4())
        await pg_backend.write_events(
            [
                _make_event(entity_refs=(ent,), timestamp_ns=10, message="a"),
                _make_event(entity_refs=(), timestamp_ns=20, message="b"),
            ]
        )
        await pg_backend.flush()
        page = await pg_backend.query_events(EventQuery(entity_uuid=ent))
        assert page.total == 1
        assert page.items[0].message == "a"

    async def test_search_text(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_events(
            [
                _make_event(message="user admin logged in", timestamp_ns=10),
                _make_event(message="server starting up", timestamp_ns=20),
            ]
        )
        await pg_backend.flush()
        results = await pg_backend.search_text("admin", limit=10)
        assert len(results) == 1
        assert "admin" in results[0].message

    async def test_search_text_empty(self, pg_backend: PostgresBackend) -> None:
        assert await pg_backend.search_text("   ", limit=10) == []

    async def test_idempotent_writes(self, pg_backend: PostgresBackend) -> None:
        e = _make_event()
        await pg_backend.write_events([e])
        await pg_backend.write_events([e])
        await pg_backend.flush()
        page = await pg_backend.query_events(EventQuery())
        assert page.total == 1


class TestModelState:
    async def test_save_load_roundtrip(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.save_state("hst:host:web-01", b"\x01\x02\x03")
        assert await pg_backend.load_state("hst:host:web-01") == b"\x01\x02\x03"

    async def test_load_missing_returns_none(self, pg_backend: PostgresBackend) -> None:
        assert await pg_backend.load_state("never-saved") is None

    async def test_overwrites_on_repeat_save(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.save_state("k", b"v1")
        await pg_backend.save_state("k", b"v2")
        assert await pg_backend.load_state("k") == b"v2"

    async def test_delete_missing_is_noop(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.delete_state("does-not-exist")  # no exception


class TestGraph:
    async def test_write_then_load(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_edge("a", "b", "talks_to", 1_000)
        await pg_backend.write_edge("a", "b", "talks_to", 2_000)  # upsert: count→2
        edges = await pg_backend.load_edges()
        assert len(edges) == 1
        src, tgt, rel, first, last, count = edges[0]
        assert (src, tgt, rel) == ("a", "b", "talks_to")
        assert first == 1_000
        assert last == 2_000
        assert count == 2


class TestAlerts:
    async def test_write_then_query(self, pg_backend: PostgresBackend) -> None:
        alert = _make_alert(dedup_key="dk-x", tactics=("execution",), techniques=("T1059",))
        is_new = await pg_backend.write_alert(alert)
        assert is_new is True

        page = await pg_backend.query_alerts(AlertQuery())
        assert page.total == 1
        assert page.items[0].dedup_key == "dk-x"

    async def test_dedup_within_window(self, pg_backend: PostgresBackend) -> None:
        a1 = _make_alert(dedup_key="dk-w", timestamp_ns=1_000_000_000)
        a2 = _make_alert(dedup_key="dk-w", timestamp_ns=1_000_001_000)
        new1 = await pg_backend.write_alert(a1, dedup_window_ns=10_000_000_000)
        new2 = await pg_backend.write_alert(a2, dedup_window_ns=10_000_000_000)
        assert new1 is True
        assert new2 is False

        page = await pg_backend.query_alerts(AlertQuery())
        assert page.total == 1
        # dedup_count should reflect the second write.
        assert page.items[0].dedup_count == 2

    async def test_filter_by_tactic(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_alert(
            _make_alert(dedup_key="t1", tactics=("execution",)),
        )
        await pg_backend.write_alert(
            _make_alert(dedup_key="t2", tactics=("defense-evasion",)),
        )
        page = await pg_backend.query_alerts(AlertQuery(tactic="execution"))
        assert page.total == 1
        assert page.items[0].dedup_key == "t1"

    async def test_get_alert_by_id(self, pg_backend: PostgresBackend) -> None:
        a = _make_alert(dedup_key="byid")
        await pg_backend.write_alert(a)
        result = await pg_backend.get_alert_by_id(a.alert_id)
        assert result is not None
        assert result.dedup_key == "byid"

    async def test_count_by_severity(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_alert(_make_alert(dedup_key="s1", severity=SeverityLevel.ERROR))
        await pg_backend.write_alert(_make_alert(dedup_key="s2", severity=SeverityLevel.ERROR))
        await pg_backend.write_alert(_make_alert(dedup_key="s3", severity=SeverityLevel.WARNING))
        counts = await pg_backend.count_by_severity()
        assert counts.get("error") == 2
        assert counts.get("warning") == 1


class TestEntityTimeline:
    async def test_timeline_returns_chronological(self, pg_backend: PostgresBackend) -> None:
        ent = str(uuid.uuid4())
        events = [
            _make_event(entity_refs=(ent,), timestamp_ns=100, message="a"),
            _make_event(entity_refs=(ent,), timestamp_ns=200, message="b"),
            _make_event(entity_refs=(ent,), timestamp_ns=50, message="c"),
        ]
        await pg_backend.write_events(events)
        await pg_backend.flush()

        timeline = await pg_backend.get_timeline(ent, TimeRange(start_ns=0, end_ns=300))
        assert [e.message for e in timeline] == ["c", "a", "b"]

    async def test_timeline_with_filters(self, pg_backend: PostgresBackend) -> None:
        ent = str(uuid.uuid4())
        await pg_backend.write_events(
            [
                _make_event(
                    entity_refs=(ent,),
                    source_type="syslog",
                    severity=SeverityLevel.INFORMATIONAL,
                    timestamp_ns=100,
                ),
                _make_event(
                    entity_refs=(ent,),
                    source_type="otlp",
                    severity=SeverityLevel.ERROR,
                    timestamp_ns=200,
                ),
            ]
        )
        await pg_backend.flush()
        only_otlp = await pg_backend.get_timeline(
            ent, TimeRange(start_ns=0, end_ns=300), source_type="otlp"
        )
        assert len(only_otlp) == 1

        only_severe = await pg_backend.get_timeline(
            ent, TimeRange(start_ns=0, end_ns=300), severity_min=SeverityLevel.ERROR
        )
        assert len(only_severe) == 1


class TestAlertsAdvanced:
    async def test_update_feedback(self, pg_backend: PostgresBackend) -> None:
        alert = _make_alert(dedup_key="fb-1")
        await pg_backend.write_alert(alert)
        await pg_backend.update_feedback(alert.alert_id, "tp", note="confirmed", origin="cli")

        fetched = await pg_backend.get_alert_by_id(alert.alert_id)
        assert fetched is not None
        assert fetched.feedback == "tp"
        assert fetched.feedback_note == "confirmed"

        page = await pg_backend.list_feedback_events(alert.alert_id)
        assert page.total == 1
        assert page.items[0].feedback == "tp"
        assert page.items[0].origin == "cli"

    async def test_update_feedback_unknown_alert_noop(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.update_feedback("does-not-exist", "fp")  # no exception

    async def test_append_feedback_event(self, pg_backend: PostgresBackend) -> None:
        alert = _make_alert(dedup_key="fb-app")
        await pg_backend.write_alert(alert)
        await pg_backend.append_feedback_event(
            alert.alert_id, "fp", "note", "api", submitted_at_ns=12345
        )
        page = await pg_backend.list_feedback_events(alert.alert_id)
        assert page.total == 1
        assert page.items[0].submitted_at_ns == 12345

    async def test_get_feedback_stats(self, pg_backend: PostgresBackend) -> None:
        a1 = _make_alert(dedup_key="s-1")
        a2 = _make_alert(dedup_key="s-2")
        await pg_backend.write_alert(a1)
        await pg_backend.write_alert(a2)
        await pg_backend.update_feedback(a1.alert_id, "tp")
        await pg_backend.update_feedback(a2.alert_id, "fp")
        stats = await pg_backend.get_feedback_stats()
        assert stats == {"tp": 1, "fp": 1, "total": 2}

    async def test_count_alerts_bucketed(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_alert(
            _make_alert(dedup_key="b-1", rule_name="r", timestamp_ns=1_000),
        )
        await pg_backend.write_alert(
            _make_alert(dedup_key="b-2", rule_name="r", timestamp_ns=2_000),
        )
        buckets = await pg_backend.count_alerts_bucketed(
            alert_type="ml",
            rule_name="r",
            time_range=TimeRange(start_ns=0, end_ns=10_000),
            bucket_ns=1_000,
        )
        # Two buckets at floor(1000/1000)*1000 = 1000 and floor(2000/1000)*1000 = 2000.
        assert len(buckets) == 2
        assert {b[0] for b in buckets} == {1_000, 2_000}

    async def test_count_alerts_bucketed_rejects_zero(self, pg_backend: PostgresBackend) -> None:
        with pytest.raises(ValueError, match="bucket_ns must be positive"):
            await pg_backend.count_alerts_bucketed(
                alert_type="ml",
                rule_name="r",
                time_range=TimeRange(start_ns=0, end_ns=1),
                bucket_ns=0,
            )

    async def test_technique_parent_rollup(self, pg_backend: PostgresBackend) -> None:
        # Parent ``T1053`` with sub-techniques ``T1053.001`` / ``T1053.005``.
        # Filtering by the parent should match the sub-technique alerts via
        # the range-bounds path.
        await pg_backend.write_alert(
            _make_alert(dedup_key="par-1", techniques=("T1053.001",)),
        )
        await pg_backend.write_alert(
            _make_alert(dedup_key="par-2", techniques=("T1053.005",)),
        )
        await pg_backend.write_alert(
            _make_alert(dedup_key="par-3", techniques=("T1059",)),
        )
        page = await pg_backend.query_alerts(AlertQuery(technique="T1053"))
        assert page.total == 2
        keys = {a.dedup_key for a in page.items}
        assert keys == {"par-1", "par-2"}

    async def test_technique_with_tactic_subtechnique(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_alert(
            _make_alert(
                dedup_key="tt-1",
                tactics=("execution",),
                techniques=("T1059.001",),
            ),
        )
        await pg_backend.write_alert(
            _make_alert(
                dedup_key="tt-2",
                tactics=("execution",),
                techniques=("T1059.002",),
            ),
        )
        page = await pg_backend.query_alerts(
            AlertQuery(tactic="execution", technique="T1059.001"),
        )
        assert page.total == 1
        assert page.items[0].dedup_key == "tt-1"

    async def test_technique_with_tactic_parent(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_alert(
            _make_alert(
                dedup_key="par-tt-1",
                tactics=("execution",),
                techniques=("T1059.001",),
            ),
        )
        await pg_backend.write_alert(
            _make_alert(
                dedup_key="par-tt-2",
                tactics=("defense-evasion",),
                techniques=("T1059.002",),
            ),
        )
        page = await pg_backend.query_alerts(
            AlertQuery(tactic="execution", technique="T1059"),
        )
        assert page.total == 1
        assert page.items[0].dedup_key == "par-tt-1"


class TestTemplates:
    async def test_write_and_get_templates(self, pg_backend: PostgresBackend) -> None:
        from seerflow.storage.sqlite import TemplateInfo

        await pg_backend.write_templates(
            [
                TemplateInfo(
                    template_id=1,
                    template_str="<*> failed login",
                    first_seen_ns=100,
                    last_seen_ns=200,
                    event_count=5,
                    example_message="user X failed login",
                )
            ]
        )
        # Upsert: write again with a higher last_seen and event_count.
        await pg_backend.write_templates(
            [
                TemplateInfo(
                    template_id=1,
                    template_str="<*> failed login",
                    first_seen_ns=999,  # overwritten as MAX; the upsert
                    last_seen_ns=300,  # leaves first_seen_ns from the original.
                    event_count=2,
                    example_message="ignored",
                )
            ]
        )
        templates = await pg_backend.get_templates()
        assert len(templates) == 1
        t = templates[0]
        assert t.template_id == 1
        assert t.event_count == 7  # 5 + 2 sum
        assert t.last_seen_ns == 300
        # first_seen_ns and example_message preserve the original discovery.
        assert t.first_seen_ns == 100
        assert t.example_message == "user X failed login"

    async def test_write_templates_empty_is_noop(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.write_templates([])
        assert await pg_backend.get_templates() == []


class TestSigmaRuleState:
    async def test_set_enabled_and_list(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.set_enabled("rule-x", False)
        await pg_backend.set_enabled("rule-y", True)
        states = await pg_backend.list_all_states()
        assert set(states.keys()) == {"rule-x", "rule-y"}
        assert states["rule-x"].enabled is False
        assert states["rule-y"].enabled is True

    async def test_record_match_accumulates(self, pg_backend: PostgresBackend) -> None:
        await pg_backend.record_match("r1", count=3, last_fired_ns=1_000)
        await pg_backend.record_match("r1", count=2, last_fired_ns=2_000)
        states = await pg_backend.list_all_states()
        s = states["r1"]
        assert s.match_count_lifetime == 5
        assert s.last_fired_ns == 2_000
