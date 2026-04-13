"""Tests for the FastAPI stats endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.stats import router
from seerflow.models.query import Page


def _make_app(log_store: AsyncMock, alert_store: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=log_store,
        alert_store=alert_store,
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestStatsEndpoint:
    """Tests for GET /api/v1/stats."""

    def test_returns_event_and_alert_counts(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(items=(), total=1000, page=1, limit=1)
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(items=(), total=42, page=1, limit=1)
        alert_store.get_feedback_stats.return_value = {"tp": 5, "fp": 3}
        app = _make_app(log_store, alert_store)
        client = TestClient(app)
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_events"] == 1000
        assert body["total_alerts"] == 42
        assert body["feedback_stats"] == {"tp": 5, "fp": 3}

    def test_empty_stats(self) -> None:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(items=(), total=0, page=1, limit=1)
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(items=(), total=0, page=1, limit=1)
        alert_store.get_feedback_stats.return_value = {}
        app = _make_app(log_store, alert_store)
        client = TestClient(app)
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 0
        assert resp.json()["total_alerts"] == 0


class TestStatsResponseSchema:
    def test_new_fields_present_and_typed(self) -> None:
        from seerflow.api.schemas import StatsResponse

        r = StatsResponse(
            total_events=10,
            total_alerts=5,
            alerts_by_severity={"high": 3},
            feedback_stats={"tp": 1},
            uptime_seconds=42.0,
            event_rate_per_sec=1.5,
            total_events_processed=100,
            active_sources=2,
            model_count=8,
        )
        assert r.uptime_seconds == 42.0
        assert r.event_rate_per_sec == 1.5
        assert r.total_events_processed == 100
        assert r.active_sources == 2
        assert r.model_count == 8

    def test_new_fields_default_to_zero(self) -> None:
        from seerflow.api.schemas import StatsResponse

        r = StatsResponse(
            total_events=0,
            total_alerts=0,
            alerts_by_severity={},
            feedback_stats={},
        )
        assert r.uptime_seconds == 0.0
        assert r.event_rate_per_sec == 0.0
        assert r.total_events_processed == 0
        assert r.active_sources == 0
        assert r.model_count == 0
