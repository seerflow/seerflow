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


class TestWebSocketWiring:
    def test_ws_manager_stored_in_app_state(self) -> None:
        from seerflow.api.ws import ConnectionManager

        manager = ConnectionManager()
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            ws_manager=manager,
        )
        assert app.state.ws_manager is manager

    def test_default_ws_manager_created_when_none_supplied(self) -> None:
        from seerflow.api.ws import ConnectionManager

        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        assert isinstance(app.state.ws_manager, ConnectionManager)

    def test_ws_route_registered(self) -> None:
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        ws_routes = [r for r in app.routes if getattr(r, "path", "") == "/api/v1/ws"]
        assert len(ws_routes) == 1

    def test_config_ws_fields_propagate_to_default_manager(self) -> None:
        """Setting ws_* fields on SeerflowConfig must reach the default ConnectionManager."""
        from seerflow.config import SeerflowConfig

        config = SeerflowConfig(
            ws_max_connections=7,
            ws_queue_maxlen=500,
            ws_tick_interval_s=0.02,
            ws_batch_max_events=3,
            ws_status_interval_s=10.0,
        )
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            config=config,
        )
        mgr = app.state.ws_manager
        assert mgr.max_connections == 7
        assert mgr._queue_maxlen == 500
        assert mgr._tick_interval_s == 0.02
        assert mgr._batch_max_events == 3
        assert mgr._status_interval_s == 10.0

    def test_explicit_ws_manager_overrides_config(self) -> None:
        """An explicit ws_manager parameter wins over config."""
        from seerflow.api.ws import ConnectionManager
        from seerflow.config import SeerflowConfig

        custom = ConnectionManager(max_connections=99)
        config = SeerflowConfig(ws_max_connections=7)
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            config=config,
            ws_manager=custom,
        )
        assert app.state.ws_manager is custom
        assert app.state.ws_manager.max_connections == 99

    def test_default_origin_allowlist_derived_from_dashboard_port(self) -> None:
        """The default ws_manager gets localhost/127.0.0.1 allowlist for dashboard_port."""
        from seerflow.config import SeerflowConfig

        config = SeerflowConfig(dashboard_port=9090)
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            config=config,
        )
        mgr = app.state.ws_manager
        assert mgr._allowed_origins == frozenset(
            {"http://localhost:9090", "http://127.0.0.1:9090"}
        )

    def test_explicit_allowed_origins_config_overrides_default(self) -> None:
        """Setting ws_allowed_origins in config replaces the localhost default."""
        from seerflow.config import SeerflowConfig

        config = SeerflowConfig(
            dashboard_port=9090,
            ws_allowed_origins=("http://dashboard.corp",),
        )
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
            config=config,
        )
        mgr = app.state.ws_manager
        assert mgr._allowed_origins == frozenset({"http://dashboard.corp"})

    def test_ws_manager_without_config_has_no_origin_check(self) -> None:
        """Passing no config preserves the permissive default for tests."""
        app = create_api_app(
            log_store=AsyncMock(),
            alert_store=AsyncMock(),
        )
        assert app.state.ws_manager._allowed_origins is None


class TestAppWiring:
    def test_config_router_registered(self) -> None:
        from seerflow.api.app import create_api_app
        from seerflow.config import SeerflowConfig

        cfg = SeerflowConfig()
        log_store = AsyncMock()
        alert_store = AsyncMock()
        app = create_api_app(log_store=log_store, alert_store=alert_store, config=cfg)
        paths = {r.path for r in app.routes}
        assert "/api/v1/config" in paths

    def test_pipeline_metrics_provider_initialized_to_none(self) -> None:
        from seerflow.api.app import create_api_app

        log_store = AsyncMock()
        alert_store = AsyncMock()
        app = create_api_app(log_store=log_store, alert_store=alert_store)
        assert getattr(app.state, "pipeline_metrics_provider", "unset") is None
