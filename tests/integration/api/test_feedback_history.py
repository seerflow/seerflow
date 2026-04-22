"""Integration tests for feedback POST + history GET (S-066)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
def client(backend: SqliteBackend) -> TestClient:
    app = create_api_app(log_store=backend, alert_store=backend)
    return TestClient(app)


async def _seed_alert(backend: SqliteBackend, *, alert_id: str = "a-1") -> str:
    eid = str(uuid.uuid4())
    alert = Alert(
        alert_id=alert_id,
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="test-rule",
        description="t",
        entity_uuid=eid,
        entity_value="192.168.1.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"hst:1:syslog:{alert_id}",
    )
    await backend.write_alert(alert, dedup_window_ns=0)
    return alert_id


async def test_post_feedback_with_origin_then_history(
    client: TestClient, backend: SqliteBackend
) -> None:
    alert_id = await _seed_alert(backend, alert_id="a-1")

    r1 = client.post(
        f"/api/v1/alerts/{alert_id}/feedback",
        json={"feedback": "tp", "origin": "dashboard"},
    )
    assert r1.status_code == 204

    r2 = client.get(f"/api/v1/alerts/{alert_id}/feedback")
    assert r2.status_code == 200
    body = r2.json()
    assert body["total"] == 1
    assert body["items"][0]["origin"] == "dashboard"
    assert body["items"][0]["feedback"] == "tp"


async def test_post_feedback_defaults_origin_to_api(
    client: TestClient, backend: SqliteBackend
) -> None:
    alert_id = await _seed_alert(backend, alert_id="a-2")
    client.post(f"/api/v1/alerts/{alert_id}/feedback", json={"feedback": "fp"})
    r = client.get(f"/api/v1/alerts/{alert_id}/feedback")
    assert r.json()["items"][0]["origin"] == "api"


async def test_get_feedback_history_404_for_missing_alert(client: TestClient) -> None:
    r = client.get("/api/v1/alerts/nope/feedback")
    assert r.status_code == 404


async def test_feedback_history_pagination(client: TestClient, backend: SqliteBackend) -> None:
    alert_id = await _seed_alert(backend, alert_id="a-3")
    for _ in range(5):
        client.post(
            f"/api/v1/alerts/{alert_id}/feedback",
            json={"feedback": "tp", "origin": "dashboard"},
        )
    r = client.get(f"/api/v1/alerts/{alert_id}/feedback?page=2&limit=2")
    body = r.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["has_next"] is True


async def test_feedback_history_rejects_limit_over_max(
    client: TestClient, backend: SqliteBackend
) -> None:
    """``limit`` above the OpenAPI-documented ceiling must 422, not silently truncate."""
    alert_id = await _seed_alert(backend, alert_id="a-5")
    r = client.get(f"/api/v1/alerts/{alert_id}/feedback?limit=500")
    assert r.status_code == 422


async def test_post_feedback_rejects_cli_origin_over_http(
    client: TestClient, backend: SqliteBackend
) -> None:
    """HTTP clients cannot forge ``origin="cli"``.

    CLI-originated feedback is written by ``process_feedback`` directly
    against the storage layer and never crosses HTTP. Accepting ``"cli"``
    on the HTTP boundary would corrupt audit-log integrity by letting any
    client impersonate the CLI source.
    """
    alert_id = await _seed_alert(backend, alert_id="a-4")
    r = client.post(
        f"/api/v1/alerts/{alert_id}/feedback",
        json={"feedback": "tp", "origin": "cli"},
    )
    assert r.status_code == 422
