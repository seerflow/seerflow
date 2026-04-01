"""Unit tests for the health endpoint handler."""

from __future__ import annotations

import json
import time

import pytest


class TestHealthHandler:
    @pytest.mark.asyncio
    async def test_returns_200(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import health_handler

        request = make_mocked_request("GET", "/api/v1/health")
        response = await health_handler(request)
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_response_is_json(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import health_handler

        request = make_mocked_request("GET", "/api/v1/health")
        response = await health_handler(request)
        assert response.content_type == "application/json"

    @pytest.mark.asyncio
    async def test_response_contains_status_healthy(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import health_handler

        request = make_mocked_request("GET", "/api/v1/health")
        response = await health_handler(request)
        body = json.loads(response.body)
        assert body["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_response_contains_components(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import health_handler

        request = make_mocked_request("GET", "/api/v1/health")
        response = await health_handler(request)
        body = json.loads(response.body)
        assert "components" in body
        assert "pipeline" in body["components"]
        assert "storage" in body["components"]

    @pytest.mark.asyncio
    async def test_response_time_under_100ms(self) -> None:
        from aiohttp.test_utils import make_mocked_request

        from seerflow.api.health import health_handler

        request = make_mocked_request("GET", "/api/v1/health")
        start = time.monotonic()
        await health_handler(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms < 100


class TestCreateHealthApp:
    def test_creates_app_with_health_route(self) -> None:
        from seerflow.api.health import create_health_app

        app = create_health_app()
        resources = [r.get_info().get("path", "") for r in app.router.resources()]
        assert "/api/v1/health" in resources
