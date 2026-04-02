"""Integration test: health server responds correctly."""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer


class TestHealthServerIntegration:
    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200(self) -> None:
        from seerflow.api.health import create_health_app

        app = create_health_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/health")
            assert resp.status == 200
            body = await resp.json()
            assert body["status"] == "healthy"
            assert "components" in body

    @pytest.mark.asyncio
    async def test_health_components_fields(self) -> None:
        from seerflow.api.health import create_health_app

        app = create_health_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/v1/health")
            body = await resp.json()
            assert body["components"]["pipeline"] == "running"
            assert body["components"]["storage"] == "connected"

    @pytest.mark.asyncio
    async def test_unknown_route_returns_404(self) -> None:
        from seerflow.api.health import create_health_app

        app = create_health_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/nonexistent")
            assert resp.status == 404
