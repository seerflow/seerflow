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
        alert_store.count_by_severity.return_value = {}
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
        alert_store.count_by_severity.return_value = {}
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


class TestStatsEndpointEnrichment:
    def _build_app(
        self,
        log_store: AsyncMock,
        alert_store: AsyncMock,
        provider=None,
    ) -> FastAPI:
        app = FastAPI()
        app.state.storage = StorageDeps(
            log_store=log_store,
            alert_store=alert_store,
        )
        app.state.pipeline_metrics_provider = provider
        app.include_router(router, prefix="/api/v1")
        return app

    def _default_stores(self) -> tuple[AsyncMock, AsyncMock]:
        log_store = AsyncMock()
        log_store.query_events.return_value = Page(items=(), total=1000, page=1, limit=1)
        alert_store = AsyncMock()
        alert_store.query_alerts.return_value = Page(items=(), total=50, page=1, limit=1)
        alert_store.get_feedback_stats.return_value = {}
        alert_store.count_by_severity.return_value = {"high": 40, "critical": 10}
        return log_store, alert_store

    def test_alerts_by_severity_populated(self) -> None:
        log_store, alert_store = self._default_stores()
        client = TestClient(self._build_app(log_store, alert_store))
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["alerts_by_severity"] == {"high": 40, "critical": 10}

    def test_metrics_provider_populates_live_fields(self) -> None:
        import time as _time

        from seerflow.api.metrics import PipelineMetrics

        log_store, alert_store = self._default_stores()
        start = _time.monotonic() - 100.0
        provider = lambda: PipelineMetrics(  # noqa: E731
            started_monotonic=start,
            total_events_processed=5000,
            active_sources=3,
            model_count=12,
        )
        client = TestClient(self._build_app(log_store, alert_store, provider=provider))
        resp = client.get("/api/v1/stats")
        body = resp.json()
        assert body["total_events_processed"] == 5000
        assert body["active_sources"] == 3
        assert body["model_count"] == 12
        assert 99.0 <= body["uptime_seconds"] <= 101.0
        assert 49.0 <= body["event_rate_per_sec"] <= 51.0

    def test_metrics_missing_returns_zero_fields(self) -> None:
        log_store, alert_store = self._default_stores()
        client = TestClient(self._build_app(log_store, alert_store, provider=None))
        resp = client.get("/api/v1/stats")
        body = resp.json()
        assert body["uptime_seconds"] == 0.0
        assert body["event_rate_per_sec"] == 0.0
        assert body["total_events_processed"] == 0
        assert body["active_sources"] == 0
        assert body["model_count"] == 0

    def test_rate_zero_when_uptime_below_one_second(self) -> None:
        import time as _time

        from seerflow.api.metrics import PipelineMetrics

        log_store, alert_store = self._default_stores()
        provider = lambda: PipelineMetrics(  # noqa: E731
            started_monotonic=_time.monotonic(),
            total_events_processed=1000,
            active_sources=1,
            model_count=4,
        )
        client = TestClient(self._build_app(log_store, alert_store, provider=provider))
        resp = client.get("/api/v1/stats")
        assert resp.json()["event_rate_per_sec"] == 0.0

    def test_count_by_severity_error_swallowed(self) -> None:
        log_store, alert_store = self._default_stores()
        alert_store.count_by_severity.side_effect = RuntimeError("db exploded")
        client = TestClient(self._build_app(log_store, alert_store))
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_events"] == 1000
        assert body["alerts_by_severity"] == {}

    def test_feedback_still_returned(self) -> None:
        log_store, alert_store = self._default_stores()
        alert_store.get_feedback_stats.return_value = {"tp": 7, "fp": 2}
        client = TestClient(self._build_app(log_store, alert_store))
        resp = client.get("/api/v1/stats")
        assert resp.json()["feedback_stats"] == {"tp": 7, "fp": 2}
