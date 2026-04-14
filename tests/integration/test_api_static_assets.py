"""Integration tests: React dashboard served alongside REST API (S-057)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import StorageConfig
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture
async def backend(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    db_path = str(tmp_path / "test_static.db")
    config = StorageConfig(backend="sqlite", sqlite_path=db_path)
    b = await SqliteBackend.connect(config)
    yield b
    await b.close()


@pytest.fixture
def fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>dashboard</title>")
    return dist


def test_root_serves_dashboard_html(backend: SqliteBackend, fake_dist: Path) -> None:
    with patch("seerflow.api.app._DEFAULT_DIST", fake_dist):
        app = create_api_app(log_store=backend, alert_store=backend)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "dashboard" in response.text


def test_health_route_still_works_with_dashboard_mounted(
    backend: SqliteBackend, fake_dist: Path
) -> None:
    with patch("seerflow.api.app._DEFAULT_DIST", fake_dist):
        app = create_api_app(log_store=backend, alert_store=backend)
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_spa_fallback_does_not_shadow_api_404s(backend: SqliteBackend, fake_dist: Path) -> None:
    with patch("seerflow.api.app._DEFAULT_DIST", fake_dist):
        app = create_api_app(log_store=backend, alert_store=backend)
    client = TestClient(app)
    # /api/v1/... is handled by FastAPI (404 JSON), NOT the SPA.
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_app_starts_without_dist(backend: SqliteBackend, tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    with patch("seerflow.api.app._DEFAULT_DIST", missing):
        app = create_api_app(log_store=backend, alert_store=backend)
    client = TestClient(app)
    assert client.get("/").status_code == 404
    assert client.get("/api/v1/health").status_code == 200
