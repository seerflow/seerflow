"""Integration test: FastAPI API with real SqliteBackend.

Verifies full round-trip: HTTP request -> FastAPI -> Storage -> response.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.entity import generate_ip_id
from seerflow.models.event import SeerflowEvent
from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
async def backend(tmp_path: Path) -> SqliteBackend:
    db_path = str(tmp_path / "test_api.db")
    config = StorageConfig(backend="sqlite", sqlite_path=db_path)
    b = await SqliteBackend.connect(config)
    yield b  # type: ignore[misc]
    await b.close()


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
        severity_id=4,
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
        assert any(item["event_id"] == str(sample_event.event_id) for item in body["items"])


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

    async def test_10k_events_under_750ms_ceiling(
        self,
        entity_client: TestClient,
        backend: SqliteBackend,
    ) -> None:
        """FR-036 target is <500ms for 10K events. 750ms ceiling absorbs CI jitter."""
        import time as _time

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

        t0 = _time.perf_counter()
        resp = entity_client.get(
            f"/api/v1/entities/{expected_uuid}/timeline"
            f"?start_ns=0&end_ns=9000000000000000000&limit=10000"
        )
        elapsed_ms = (_time.perf_counter() - t0) * 1000.0

        assert resp.status_code == 200
        assert resp.json()["total"] == 10_000
        assert elapsed_ms < 750, f"timeline took {elapsed_ms:.0f}ms (>=750ms)"
