"""Tests for the FastAPI app factory."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app


def _make_client() -> TestClient:
    app = create_api_app(
        log_store=AsyncMock(),
        alert_store=AsyncMock(),
    )
    return TestClient(app)


class TestAppFactory:
    """Tests for create_api_app."""

    def test_creates_fastapi_app(self) -> None:
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        assert isinstance(app, FastAPI)

    def test_openapi_accessible(self) -> None:
        client = _make_client()
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "Seerflow API"

    def test_docs_accessible(self) -> None:
        client = _make_client()
        resp = client.get("/api/v1/docs")
        assert resp.status_code == 200

    def test_health_route_registered(self) -> None:
        client = _make_client()
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_cors_headers_present(self) -> None:
        client = _make_client()
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" in resp.headers

    def test_storage_deps_on_state(self) -> None:
        log_store = AsyncMock()
        alert_store = AsyncMock()
        app = create_api_app(log_store=log_store, alert_store=alert_store)
        assert app.state.storage.log_store is log_store
        assert app.state.storage.alert_store is alert_store

    def test_entity_store_optional(self) -> None:
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        assert app.state.storage.entity_store is None

    def test_all_route_prefixes_registered(self) -> None:
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        paths = {route.path for route in app.routes}
        assert "/api/v1/events" in paths
        assert "/api/v1/alerts" in paths
        assert "/api/v1/alerts/{alert_id}" in paths
        assert "/api/v1/alerts/{alert_id}/feedback" in paths
        assert "/api/v1/entities/search" in paths
        assert "/api/v1/health" in paths
        assert "/api/v1/stats" in paths
