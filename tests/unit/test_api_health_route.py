"""Tests for the FastAPI health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import DetectionEngines, StorageDeps
from seerflow.api.routes.health import router


def _make_app(health_state: dict[str, str]) -> FastAPI:
    app = FastAPI()
    app.state.health_state = health_state
    app.state.engines = DetectionEngines()
    alert_store = MagicMock()
    alert_store.get_feedback_stats = AsyncMock(return_value={"tp": 0, "fp": 0})
    app.state.storage = StorageDeps(log_store=MagicMock(), alert_store=alert_store)
    app.include_router(router, prefix="/api/v1")
    return app


def _make_app_with_extras(
    *,
    ensemble: object | None,
    alert_store: object | None = None,
) -> FastAPI:
    """Build a minimal app for health-route tests.

    ``alert_store`` defaults to a stub returning empty feedback stats — the
    route now relies on the contract that ``StorageDeps.alert_store`` is
    always present (matches the ``create_api_app`` factory signature).
    """
    app = FastAPI()
    app.state.health_state = {"pipeline": "running", "storage": "connected"}
    app.state.engines = DetectionEngines(
        sigma_engine=None,
        correlation_rules=(),
        ensemble=ensemble,
    )
    if alert_store is None:
        alert_store = MagicMock()
        alert_store.get_feedback_stats = AsyncMock(return_value={})
    app.state.storage = StorageDeps(log_store=MagicMock(), alert_store=alert_store)
    app.include_router(router, prefix="/api/v1")
    return app


class TestHealthEndpoint:
    """Tests for GET /api/v1/health."""

    def test_all_healthy_returns_200(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "connected"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["components"]["pipeline"] == "running"

    def test_degraded_returns_503(self) -> None:
        app = _make_app({"pipeline": "running", "storage": "error"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 503
        assert resp.json()["status"] == "degraded"

    def test_ok_status_counts_as_healthy(self) -> None:
        app = _make_app({"pipeline": "ok"})
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


class TestHealthEndpointExtras:
    """S-217 — /api/v1/health surfaces detection + feedback when wired."""

    def test_includes_detection_when_ensemble_wired(self) -> None:
        ensemble = MagicMock()
        ensemble.get_health.return_value = {"detectors": 4, "models_loaded": 7}
        alert_store = MagicMock()
        alert_store.get_feedback_stats = AsyncMock(return_value={"tp": 1, "fp": 2})
        client = TestClient(_make_app_with_extras(ensemble=ensemble, alert_store=alert_store))

        body = client.get("/api/v1/health").json()
        assert body["detection"] == {"detectors": 4, "models_loaded": 7}
        assert body["feedback"] == {"tp": 1, "fp": 2}

    def test_detection_is_none_when_ensemble_missing(self) -> None:
        """When no ``DetectionEnsemble`` is wired, ``detection`` falls back to ``None``;
        ``feedback`` always populates because ``alert_store`` is non-Optional by contract."""
        client = TestClient(_make_app_with_extras(ensemble=None))
        body = client.get("/api/v1/health").json()
        assert body["detection"] is None
        assert body["feedback"] == {}
