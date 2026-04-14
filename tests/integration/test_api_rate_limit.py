"""Integration tests for per-endpoint rate limiting (S-181)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import SeerflowConfig, StorageConfig
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "rl.db"))
    b = await SqliteBackend.connect(cfg)
    yield b
    await b.close()


def _client(backend: SqliteBackend, **overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_rate_limit_enabled": True,
        "api_list_rate_limit": "2/minute",
        "api_detail_rate_limit": "100/minute",
        "api_allowed_origins": ("http://localhost:3000",),
    }
    defaults.update(overrides)
    cfg = SeerflowConfig(**defaults)  # type: ignore[arg-type]
    app = create_api_app(log_store=backend, alert_store=backend, config=cfg)
    return TestClient(app)


class TestRateLimit:
    async def test_list_endpoint_429_after_limit_exceeded(self, backend: SqliteBackend) -> None:
        client = _client(backend)
        r1 = client.get("/api/v1/alerts")
        r2 = client.get("/api/v1/alerts")
        r3 = client.get("/api/v1/alerts")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        assert "retry-after" in {k.lower() for k in r3.headers}

    async def test_health_endpoint_not_rate_limited(self, backend: SqliteBackend) -> None:
        client = _client(backend)
        for _ in range(10):
            r = client.get("/api/v1/health")
            assert r.status_code == 200

    async def test_openapi_endpoint_not_rate_limited(self, backend: SqliteBackend) -> None:
        client = _client(backend)
        for _ in range(10):
            r = client.get("/api/v1/openapi.json")
            assert r.status_code == 200

    async def test_different_ips_throttled_independently(self, backend: SqliteBackend) -> None:
        client = _client(backend, api_trust_proxy_headers=True)
        # Client A — exhausts limit
        for _ in range(2):
            r = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "203.0.113.1"})
            assert r.status_code == 200
        r3 = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "203.0.113.1"})
        assert r3.status_code == 429
        # Client B — still allowed
        r_b = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "198.51.100.7"})
        assert r_b.status_code == 200

    async def test_list_and_detail_have_independent_budgets(self, backend: SqliteBackend) -> None:
        client = _client(backend)
        for _ in range(2):
            assert client.get("/api/v1/alerts").status_code == 200
        assert client.get("/api/v1/alerts").status_code == 429
        # Detail endpoint uses `detail_limit` (100/minute) — still allowed.
        r = client.get("/api/v1/alerts/nonexistent-id")
        assert r.status_code == 404

    async def test_rate_limiter_disabled_does_not_throttle(self, backend: SqliteBackend) -> None:
        client = _client(backend, api_rate_limit_enabled=False)
        for _ in range(5):
            assert client.get("/api/v1/alerts").status_code == 200
