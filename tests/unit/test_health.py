"""Unit tests for the health endpoint handler."""

from __future__ import annotations

import json

import pytest

from seerflow.api.health import _HEALTH_STATE_KEY, create_health_app, health_handler


class TestHealthHandlerHealthy:
    """Tests when all components report healthy status."""

    @pytest.fixture
    def app(self):
        return create_health_app()

    @pytest.mark.asyncio
    async def test_returns_200(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_response_is_json(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_response_contains_status_healthy(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_response_contains_components(self, app) -> None:
        from aiohttp.test_utils import make_mocked_request

        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "components" in body
        assert "pipeline" in body["components"]
        assert "storage" in body["components"]


class TestHealthHandlerDegraded:
    """Tests when a component reports unhealthy status → HTTP 503."""

    @pytest.mark.asyncio
    async def test_returns_503_when_pipeline_stopped(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "stopped", "storage": "connected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 503

    @pytest.mark.asyncio
    async def test_returns_degraded_status(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "stopped", "storage": "connected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_returns_503_when_storage_disconnected(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        app = create_health_app(state={"pipeline": "running", "storage": "disconnected"})
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        assert response.status == 503

    @pytest.mark.asyncio
    async def test_component_values_reflected_in_response(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        state = {"pipeline": "stopped", "storage": "error"}
        app = create_health_app(state=state)
        request = make_mocked_request("GET", "/api/v1/health", app=app)
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["components"]["pipeline"] == "stopped"
        assert body["components"]["storage"] == "error"


class TestCreateHealthApp:
    def test_creates_app_with_health_route(self) -> None:
        app = create_health_app()
        resources = [r.get_info().get("path", "") for r in app.router.resources()]
        assert "/api/v1/health" in resources

    def test_custom_state_injected(self) -> None:
        state = {"pipeline": "stopped"}
        app = create_health_app(state=state)
        assert app[_HEALTH_STATE_KEY] is state

    def test_default_state_is_healthy(self) -> None:
        app = create_health_app()
        assert app[_HEALTH_STATE_KEY]["pipeline"] == "running"
        assert app[_HEALTH_STATE_KEY]["storage"] == "connected"
