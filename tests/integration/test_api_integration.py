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
