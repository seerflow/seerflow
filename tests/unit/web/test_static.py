"""Unit tests for seerflow.web.static (S-057)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.web.static import mount_dashboard

if TYPE_CHECKING:
    from pathlib import Path


def _write_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>test</title>")
    (dist / "app.js").write_text("console.log('ok');")
    return dist


def test_mount_returns_false_when_dist_missing(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_dashboard(app, dist_dir=tmp_path / "does-not-exist") is False
    client = TestClient(app)
    assert client.get("/").status_code == 404


def test_mount_serves_index_for_root(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_dashboard(app, dist_dir=_write_dist(tmp_path)) is True
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text


def test_mount_serves_static_asset(tmp_path: Path) -> None:
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_spa_fallback_returns_index_for_unknown_path(tmp_path: Path) -> None:
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/unknown/deep/route")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text


def test_api_prefix_does_not_get_spa_fallback(tmp_path: Path) -> None:
    """Paths under ``/api/`` must return 404, never the SPA index.

    Guards against a regression where the SPA fallback swallows API
    misses and breaks JSON clients.
    """
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404


def test_api_prefix_bypass_variants_also_return_404(tmp_path: Path) -> None:
    """Bypass attempts must still 404 — not fall back to index.html.

    Covers: bare ``/api`` (no trailing slash), upper-case ``/API/...``,
    and percent-encoded variants (``/%61pi/...`` where ``%61`` == 'a',
    ``/api%2Fv1/...`` where ``%2F`` == '/'). Locks the API-vs-SPA gate
    against URL-decoding regressions (SEE-245).
    """
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    for url in (
        "/api",
        "/API/v1/x",
        "/API",
        "/%61pi/v1/missing",
        "/api%2Fv1/missing",
    ):
        response = client.get(url)
        assert response.status_code == 404, (
            f"expected 404 for {url!r}, got {response.status_code} "
            f"(body starts with {response.text[:40]!r})"
        )


def test_spa_index_sends_no_cache_header(tmp_path: Path) -> None:
    """The SPA shell must not be cached — asset hashes rotate on deploy."""
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/some/client-route")
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "").lower()
