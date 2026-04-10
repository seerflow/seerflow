"""Tests for the FastAPI stats endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.stats import router
from seerflow.models.query import Page


def _make_app(alert_store: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.state.storage = StorageDeps(
        log_store=AsyncMock(),
        alert_store=alert_store,
    )
    app.include_router(router, prefix="/api/v1")
    return app


class TestStatsEndpoint:
    """Tests for GET /api/v1/stats."""

    def test_returns_alert_counts(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(items=(), total=42, page=1, limit=1)
        alert_store.get_feedback_stats.return_value = {"tp": 5, "fp": 3}
        app = _make_app(alert_store)
        client = TestClient(app)
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_alerts"] == 42
        assert body["feedback_stats"] == {"tp": 5, "fp": 3}

    def test_empty_stats(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(items=(), total=0, page=1, limit=1)
        alert_store.get_feedback_stats.return_value = {}
        app = _make_app(alert_store)
        client = TestClient(app)
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["total_alerts"] == 0
