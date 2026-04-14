"""Integration tests for the narrowed CORS allowlist (S-181)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from seerflow.api.app import create_api_app
from seerflow.config import SeerflowConfig, StorageConfig
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "cors.db"))
    b = await SqliteBackend.connect(cfg)
    yield b
    await b.close()


def _client(backend: SqliteBackend, **overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_rate_limit_enabled": False,
        "api_allowed_origins": ("https://dash.example.com",),
    }
    defaults.update(overrides)
    cfg = SeerflowConfig(**defaults)  # type: ignore[arg-type]
    app = create_api_app(log_store=backend, alert_store=backend, config=cfg)
    return TestClient(app)


class TestCors:
    async def test_preflight_allowed_origin_returns_acao_header(
        self, backend: SqliteBackend
    ) -> None:
        client = _client(backend)
        r = client.options(
            "/api/v1/alerts",
            headers={
                "Origin": "https://dash.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "https://dash.example.com"

    async def test_preflight_disallowed_origin_omits_acao_header(
        self, backend: SqliteBackend
    ) -> None:
        client = _client(backend)
        r = client.options(
            "/api/v1/alerts",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}

    async def test_wildcard_not_in_middleware_config(self, backend: SqliteBackend) -> None:
        client = _client(backend, api_allowed_origins=("http://localhost:3000",))
        app = client.app
        cors_mw = next(mw for mw in app.user_middleware if mw.cls is CORSMiddleware)
        origins = cors_mw.kwargs["allow_origins"]
        assert "*" not in origins
        assert "http://localhost:3000" in origins

    async def test_cors_falls_back_to_ws_origins_when_api_unset(
        self, backend: SqliteBackend
    ) -> None:
        client = _client(
            backend,
            api_allowed_origins=(),
            ws_allowed_origins=("https://ws.example.com",),
        )
        r = client.options(
            "/api/v1/alerts",
            headers={
                "Origin": "https://ws.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "https://ws.example.com"
