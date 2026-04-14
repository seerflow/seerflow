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
            r = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "8.8.8.8"})
            assert r.status_code == 200
        r3 = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "8.8.8.8"})
        assert r3.status_code == 429
        # Client B — still allowed
        r_b = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "1.1.1.1"})
        assert r_b.status_code == 200

    async def test_spoofed_loopback_xff_does_not_bypass_limit(
        self, backend: SqliteBackend
    ) -> None:
        """Security: attacker setting XFF=127.0.0.1 cannot hide from throttle."""
        client = _client(backend, api_trust_proxy_headers=True)
        # Both requests share the TestClient 'testclient' client.host bucket
        # because XFF=127.0.0.1 is rejected as non-public.
        for _ in range(2):
            r = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "127.0.0.1"})
            assert r.status_code == 200
        r3 = client.get("/api/v1/alerts", headers={"X-Forwarded-For": "127.0.0.1"})
        assert r3.status_code == 429

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

    async def test_attack_coverage_429_matches_ac_spec(self, backend: SqliteBackend) -> None:
        """AC #7 traceability: 429 on /attack/coverage at 2/min."""
        client = _client(backend)
        for _ in range(2):
            assert client.get("/api/v1/attack/coverage").status_code == 200
        r3 = client.get("/api/v1/attack/coverage")
        assert r3.status_code == 429
        assert "retry-after" in {k.lower() for k in r3.headers}

    async def test_openapi_documents_429_for_rate_limited_routes(
        self, backend: SqliteBackend
    ) -> None:
        """AC #8: OpenAPI schema lists 429 on every rate-limited route."""
        client = _client(backend, api_rate_limit_enabled=False)
        schema = client.get("/api/v1/openapi.json").json()
        rate_limited_paths = (
            "/api/v1/alerts",
            "/api/v1/alerts/{alert_id}",
            "/api/v1/events",
            "/api/v1/entities/search",
            "/api/v1/attack/coverage",
            "/api/v1/stats",
            "/api/v1/config",
        )
        paths = schema["paths"]
        for path in rate_limited_paths:
            assert path in paths, f"missing route {path} from OpenAPI schema"
            # Any method operation on the path must document 429.
            for method_op in paths[path].values():
                responses = method_op.get("responses", {})
                assert "429" in responses, f"{path} missing 429 response in OpenAPI schema"
