"""Integration test: FastAPI API with real SqliteBackend.

Verifies full round-trip: HTTP request -> FastAPI -> Storage -> response.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.entity import generate_ip_id
from seerflow.models.event import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
def client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
    )
    return TestClient(app)


@pytest.fixture
def sample_event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_775_736_000_000_000_000,
        observed_ns=1_775_736_000_000_000_001,
        message="Integration test event",
        source_type="syslog",
        related_ips=("10.0.0.1",),
    )


@pytest.fixture
def sample_alert() -> Alert:
    return Alert(
        alert_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "integration-test")),
        alert_type="ml",
        timestamp_ns=1_775_736_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name="hst_anomaly",
        description="Integration test alert",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "10.0.0.1")),
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        risk_score=0.75,
    )


class TestEventsIntegration:
    """Full round-trip event queries."""

    async def test_write_then_query(
        self, client: TestClient, backend: SqliteBackend, sample_event: SeerflowEvent
    ) -> None:
        await backend.write_events([sample_event])
        await backend.flush()
        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        item = next(i for i in body["items"] if i["event_id"] == str(sample_event.event_id))
        assert isinstance(item["timestamp_ns"], str)
        assert isinstance(item["observed_ns"], str)
        assert item["timestamp_ns"] == str(sample_event.timestamp_ns)
        assert item["observed_ns"] == str(sample_event.observed_ns)


class TestAlertsIntegration:
    """Full round-trip alert queries."""

    async def test_write_then_query(
        self, client: TestClient, backend: SqliteBackend, sample_alert: Alert
    ) -> None:
        await backend.write_alert(sample_alert, dedup_window_ns=0)
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

    async def test_get_alert_by_id(
        self, client: TestClient, backend: SqliteBackend, sample_alert: Alert
    ) -> None:
        await backend.write_alert(sample_alert, dedup_window_ns=0)
        resp = client.get(f"/api/v1/alerts/{sample_alert.alert_id}")
        assert resp.status_code == 200
        assert resp.json()["alert_id"] == sample_alert.alert_id

    async def test_feedback_round_trip(
        self, client: TestClient, backend: SqliteBackend, sample_alert: Alert
    ) -> None:
        await backend.write_alert(sample_alert, dedup_window_ns=0)
        resp = client.post(
            f"/api/v1/alerts/{sample_alert.alert_id}/feedback",
            json={"feedback": "tp"},
        )
        assert resp.status_code == 204

    async def test_filter_by_tactic(self, client: TestClient, backend: SqliteBackend) -> None:
        a1 = Alert(
            alert_id="int-mitre-a1",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("discovery",),
            mitre_techniques=("t1033",),
            dedup_key="int-mitre:a1",
        )
        a2 = Alert(
            alert_id="int-mitre-a2",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_001,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("execution",),
            mitre_techniques=("t1059",),
            dedup_key="int-mitre:a2",
        )
        await backend.write_alert(a1, dedup_window_ns=0)
        await backend.write_alert(a2, dedup_window_ns=0)
        resp = client.get("/api/v1/alerts", params={"tactic": "discovery"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert [item["alert_id"] for item in body["items"]] == ["int-mitre-a1"]

    async def test_filter_by_technique_case_insensitive(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        a1 = Alert(
            alert_id="int-tech-a1",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("discovery",),
            mitre_techniques=("t1033",),
            dedup_key="int-tech:a1",
        )
        a2 = Alert(
            alert_id="int-tech-a2",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_001,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("discovery",),
            mitre_techniques=("t1087",),
            dedup_key="int-tech:a2",
        )
        await backend.write_alert(a1, dedup_window_ns=0)
        await backend.write_alert(a2, dedup_window_ns=0)
        resp = client.get("/api/v1/alerts", params={"technique": "T1033"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["alert_id"] == "int-tech-a1"

    async def test_filter_by_parent_technique_rolls_subs_in(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        a_parent = Alert(
            alert_id="rollup-parent-flt",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1053",),
            dedup_key="rollup-flt:parent",
        )
        a_sub = Alert(
            alert_id="rollup-sub-flt",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_001,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1053.005",),
            dedup_key="rollup-flt:sub",
        )
        a_other = Alert(
            alert_id="other-flt",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_002,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1059",),
            dedup_key="rollup-flt:other",
        )
        await backend.write_alert(a_parent, dedup_window_ns=0)
        await backend.write_alert(a_sub, dedup_window_ns=0)
        await backend.write_alert(a_other, dedup_window_ns=0)

        resp = client.get("/api/v1/alerts", params={"technique": "T1053"})
        assert resp.status_code == 200
        body = resp.json()
        ids = {item["alert_id"] for item in body["items"]}
        assert ids == {"rollup-parent-flt", "rollup-sub-flt"}
        assert body["total"] == 2

    async def test_filter_by_subtechnique_exact_match_backward_compat(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        a_parent = Alert(
            alert_id="bc-parent",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1053",),
            dedup_key="bc:parent",
        )
        a_sub = Alert(
            alert_id="bc-sub",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_001,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1053.005",),
            dedup_key="bc:sub",
        )
        await backend.write_alert(a_parent, dedup_window_ns=0)
        await backend.write_alert(a_sub, dedup_window_ns=0)

        resp = client.get("/api/v1/alerts", params={"technique": "T1053.005"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["alert_id"] == "bc-sub"

    async def test_filter_by_parent_technique_dedups_parent_and_sub_on_same_alert(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        # Alert tagged with BOTH parent T1053 and sub T1053.005 must be
        # returned exactly once when filtered by the parent (not twice, once
        # for each junction-table row).
        a_both = Alert(
            alert_id="both-tags",
            alert_type="sigma",
            timestamp_ns=1_775_736_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="test",
            description="",
            entity_uuid="e1",
            entity_value="1.2.3.4",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("persistence",),
            mitre_techniques=("T1053", "T1053.005"),
            dedup_key="both:1",
        )
        await backend.write_alert(a_both, dedup_window_ns=0)

        resp = client.get("/api/v1/alerts", params={"technique": "T1053"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert [item["alert_id"] for item in body["items"]] == ["both-tags"]


class TestHealthIntegration:
    """Health endpoint with real app."""

    def test_health_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestStatsIntegration:
    """Stats endpoint with real storage."""

    async def test_stats_with_alerts(
        self, client: TestClient, backend: SqliteBackend, sample_alert: Alert
    ) -> None:
        await backend.write_alert(sample_alert, dedup_window_ns=0)
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["total_alerts"] >= 1


@pytest.fixture
def entity_client(backend: SqliteBackend) -> TestClient:
    """Client with entity_store wired to the SqliteBackend."""
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        entity_store=backend,
    )
    return TestClient(app)


class TestEntityTimelineIntegration:
    """End-to-end: ingest -> search -> follow -> timeline."""

    async def test_search_then_timeline_round_trip(
        self,
        entity_client: TestClient,
        backend: SqliteBackend,
    ) -> None:
        ip = "192.168.42.7"
        expected_uuid = str(generate_ip_id(ip))

        events = [
            SeerflowEvent(
                event_id=uuid.uuid4(),
                timestamp_ns=1_775_736_000_000_000_000 + i * 1_000_000_000,
                observed_ns=1_775_736_000_000_000_001 + i * 1_000_000_000,
                message=f"ssh login attempt {i} from {ip}",
                source_type="auth" if i % 2 == 0 else "syslog",
                related_ips=(ip,),
                entity_refs=(expected_uuid,),
            )
            for i in range(5)
        ]
        await backend.write_events(events)
        await backend.flush()

        search_resp = entity_client.get(f"/api/v1/entities/search?q={ip}")
        assert search_resp.status_code == 200
        matches = [r for r in search_resp.json() if r["entity_value"] == ip]
        assert len(matches) == 1
        entity_uuid = matches[0]["entity_uuid"]
        assert entity_uuid == expected_uuid

        timeline_resp = entity_client.get(
            f"/api/v1/entities/{entity_uuid}/timeline?start_ns=0&end_ns=9000000000000000000"
        )
        assert timeline_resp.status_code == 200
        body = timeline_resp.json()
        assert body["entity_uuid"] == entity_uuid
        assert body["total"] == 5
        timestamps = [e["timestamp_ns"] for e in body["events"]]
        assert timestamps == sorted(timestamps)
        source_types = {e["source_type"] for e in body["events"]}
        assert source_types == {"auth", "syslog"}

    async def test_timeline_source_type_filter(
        self,
        entity_client: TestClient,
        backend: SqliteBackend,
    ) -> None:
        ip = "192.168.42.8"
        expected_uuid = str(generate_ip_id(ip))
        events = [
            SeerflowEvent(
                event_id=uuid.uuid4(),
                timestamp_ns=1_775_736_000_000_000_000 + i * 1_000_000_000,
                observed_ns=1_775_736_000_000_000_001 + i * 1_000_000_000,
                message=f"msg {i}",
                source_type="auth" if i % 2 == 0 else "syslog",
                related_ips=(ip,),
                entity_refs=(expected_uuid,),
            )
            for i in range(4)
        ]
        await backend.write_events(events)
        await backend.flush()

        resp = entity_client.get(
            f"/api/v1/entities/{expected_uuid}/timeline"
            f"?start_ns=0&end_ns=9000000000000000000&source_type=auth"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(e["source_type"] == "auth" for e in body["events"])

    @pytest.mark.slow
    async def test_10k_events_under_750ms_ceiling(
        self,
        entity_client: TestClient,
        backend: SqliteBackend,
    ) -> None:
        """FR-036 target is <500ms for 10K events. 750ms ceiling absorbs CI jitter."""
        ip = "192.168.99.1"
        expected_uuid = str(generate_ip_id(ip))
        batch = 1_000
        for b in range(10):
            events = [
                SeerflowEvent(
                    event_id=uuid.uuid4(),
                    timestamp_ns=1_775_736_000_000_000_000 + (b * batch + i) * 1_000_000,
                    observed_ns=1_775_736_000_000_000_001 + (b * batch + i) * 1_000_000,
                    message="bulk event",
                    source_type="syslog",
                    related_ips=(ip,),
                    entity_refs=(expected_uuid,),
                )
                for i in range(batch)
            ]
            await backend.write_events(events)
        await backend.flush()

        warmup = entity_client.get(
            f"/api/v1/entities/{expected_uuid}/timeline"
            f"?start_ns=0&end_ns=9000000000000000000&limit=10000"
        )
        assert warmup.status_code == 200

        t0 = time.perf_counter()
        resp = entity_client.get(
            f"/api/v1/entities/{expected_uuid}/timeline"
            f"?start_ns=0&end_ns=9000000000000000000&limit=10000"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert resp.status_code == 200
        assert resp.json()["total"] == 10_000
        assert elapsed_ms < 750, f"timeline took {elapsed_ms:.0f}ms (>=750ms)"


class TestConfigAndStatsIntegration:
    """End-to-end: config + stats against a real SqliteBackend."""

    async def test_config_endpoint_masks_secrets(
        self, client: TestClient, backend: SqliteBackend
    ) -> None:
        from seerflow.config import AlertingConfig, SeerflowConfig

        cfg = SeerflowConfig(
            storage=StorageConfig(
                backend="postgresql",
                postgresql_url="postgres://u:CANARY_PG_SECRET@h/d",
            ),
            alerting=AlertingConfig(pagerduty_routing_key="CANARY_PD_KEY"),
        )
        app = create_api_app(
            log_store=backend,
            alert_store=backend,
            config=cfg,
        )
        local_client = TestClient(app)
        resp = local_client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["storage"]["postgresql_url"] == "***"
        assert body["alerting"]["pagerduty_routing_key"] == "***"
        assert b"CANARY_PG_SECRET" not in resp.content
        assert b"CANARY_PD_KEY" not in resp.content

    async def test_stats_endpoint_end_to_end(self, backend: SqliteBackend) -> None:
        from seerflow.api.metrics import PipelineMetrics
        from seerflow.config import SeerflowConfig

        def _alert(idx: int, sev: SeverityLevel, tag: str) -> Alert:
            return Alert(
                alert_id=f"stats-{tag}-{idx}",
                alert_type="ml",
                timestamp_ns=1_775_736_000_000_000_000 + idx,
                severity_id=sev,
                rule_name="hst_anomaly",
                description=f"{tag} alert {idx}",
                entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"stats-{tag}-{idx}")),
                entity_value="10.0.0.1",
                entity_type="ip",
                contributing_events=(),
                dedup_key=f"stats:{tag}:{idx}",
            )

        for i in range(3):
            await backend.write_alert(_alert(i, SeverityLevel.ERROR, "e"), dedup_window_ns=0)
        for i in range(2):
            await backend.write_alert(_alert(i, SeverityLevel.CRITICAL, "c"), dedup_window_ns=0)
        await backend.write_alert(_alert(0, SeverityLevel.WARNING, "w"), dedup_window_ns=0)

        app = create_api_app(
            log_store=backend,
            alert_store=backend,
            config=SeerflowConfig(),
        )
        start = time.monotonic() - 50.0
        app.state.pipeline_metrics_provider = lambda: PipelineMetrics(
            started_monotonic=start,
            total_events_processed=10,
            active_sources=2,
            model_count=8,
        )
        local_client = TestClient(app)
        resp = local_client.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_alerts"] == 6
        assert body["alerts_by_severity"] == {"error": 3, "critical": 2, "warning": 1}
        assert body["total_events_processed"] == 10
        assert body["active_sources"] == 2
        assert body["model_count"] == 8
        assert 49.0 <= body["uptime_seconds"] <= 51.0
        assert 0.15 <= body["event_rate_per_sec"] <= 0.25

    async def test_both_endpoints_under_100ms(self, backend: SqliteBackend) -> None:
        """FR-047 target is <50ms; CI ceiling of 100ms absorbs runner jitter."""
        from seerflow.config import SeerflowConfig

        app = create_api_app(
            log_store=backend,
            alert_store=backend,
            config=SeerflowConfig(),
        )
        local_client = TestClient(app)
        for path in ("/api/v1/config", "/api/v1/stats"):
            t0 = time.perf_counter()
            resp = local_client.get(path)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200
            assert elapsed_ms < 100, f"{path} took {elapsed_ms:.1f}ms"
