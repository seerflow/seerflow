"""Tests for the FastAPI alerts endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.alerts import router
from seerflow.models.alert import Alert
from seerflow.models.query import Page


def _make_alert(**overrides) -> Alert:
    defaults = {
        "alert_id": "alert-001",
        "alert_type": "ml",
        "timestamp_ns": 1_000_000_000,
        "severity_id": 4,
        "rule_name": "hst_anomaly",
        "description": "Anomaly detected",
        "entity_uuid": "ent-001",
        "entity_value": "192.168.1.1",
        "entity_type": "ip",
        "contributing_events": (uuid.uuid4(),),
        "risk_score": 0.85,
    }
    defaults.update(overrides)
    return Alert(**defaults)


def _make_app(alert_store: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=AsyncMock(),
        alert_store=alert_store,
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestListAlerts:
    """Tests for GET /api/v1/alerts."""

    def test_default_params(self) -> None:
        alert = _make_alert()
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(
            items=(alert,),
            total=1,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["alert_id"] == "alert-001"

    def test_type_filter(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?type=sigma")
        assert resp.status_code == 200
        call_args = alert_store.query_alerts.call_args[0][0]
        assert call_args.alert_type == "sigma"

    def test_invalid_type_returns_422(self) -> None:
        alert_store = AsyncMock()
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?type=garbage")
        assert resp.status_code == 422

    def test_since_until_filtering(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=50,
        )
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?since=2026-04-09T00:00:00&until=2026-04-09T23:59:59")
        assert resp.status_code == 200
        call_args = alert_store.query_alerts.call_args[0][0]
        assert call_args.time_range is not None
        assert call_args.time_range.start_ns < call_args.time_range.end_ns

    def test_since_after_until_returns_400(self) -> None:
        alert_store = AsyncMock()
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?since=2026-04-10T00:00:00&until=2026-04-09T00:00:00")
        assert resp.status_code == 400

    def test_invalid_timestamp_returns_422(self) -> None:
        alert_store = AsyncMock()
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?since=garbage")
        assert resp.status_code == 422

    def test_limit_capped_at_1000(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(
            items=(),
            total=0,
            page=1,
            limit=1000,
        )
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts?limit=5000")
        assert resp.status_code == 200
        call_args = alert_store.query_alerts.call_args[0][0]
        assert call_args.limit == 1000


class TestGetAlert:
    """Tests for GET /api/v1/alerts/{alert_id}."""

    def test_existing_alert(self) -> None:
        alert = _make_alert()
        alert_store = AsyncMock()
        alert_store.get_alert_by_id.return_value = alert
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts/alert-001")
        assert resp.status_code == 200
        assert resp.json()["alert_id"] == "alert-001"

    def test_not_found(self) -> None:
        alert_store = AsyncMock()
        alert_store.get_alert_by_id.return_value = None
        client = TestClient(_make_app(alert_store))
        resp = client.get("/api/v1/alerts/nonexistent")
        assert resp.status_code == 404


class TestAlertFeedback:
    """Tests for POST /api/v1/alerts/{alert_id}/feedback."""

    def test_submit_tp_feedback(self) -> None:
        alert_store = AsyncMock()
        alert_store.get_alert_by_id.return_value = _make_alert()
        alert_store.update_feedback.return_value = None
        client = TestClient(_make_app(alert_store))
        resp = client.post(
            "/api/v1/alerts/alert-001/feedback",
            json={"feedback": "tp"},
        )
        assert resp.status_code == 204
        alert_store.update_feedback.assert_called_once_with("alert-001", "tp")

    def test_feedback_alert_not_found(self) -> None:
        alert_store = AsyncMock()
        alert_store.get_alert_by_id.return_value = None
        client = TestClient(_make_app(alert_store))
        resp = client.post(
            "/api/v1/alerts/alert-001/feedback",
            json={"feedback": "fp"},
        )
        assert resp.status_code == 404

    def test_invalid_feedback_rejected(self) -> None:
        alert_store = AsyncMock()
        client = TestClient(_make_app(alert_store))
        resp = client.post(
            "/api/v1/alerts/alert-001/feedback",
            json={"feedback": "invalid"},
        )
        assert resp.status_code == 422
