"""Tests for the FastAPI health endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.routes.health import router


def _make_app(health_state: dict[str, str]) -> FastAPI:
    app = FastAPI()
    app.state.health_state = health_state
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
