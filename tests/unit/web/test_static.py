"""Unit tests for seerflow.web.static (S-057)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.web.middleware import CollapseSlashesMiddleware
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


@pytest.mark.parametrize(
    "url",
    [
        "/api",
        "/API",
        "/API/v1/x",
        "/%61pi/v1/missing",
        "/api%2Fv1/missing",
    ],
)
def test_api_prefix_bypass_variants_also_return_404(tmp_path: Path, url: str) -> None:
    """Bypass attempts must still 404 — not fall back to ``index.html``.

    Covers: bare ``/api`` (no trailing slash), upper-case ``/API/...``,
    and percent-encoded variants (``/%61pi/...`` where ``%61`` == 'a';
    ``/api%2Fv1/...`` where ``%2F`` == '/'). Locks the API-vs-SPA
    gate against URL-decoding regressions (SEE-245).

    Leading-multi-slash variants (``//api/v1/x``, ``///api/v1/x``)
    are exercised separately in
    ``test_collapses_leading_multi_slash_path_at_app_level`` —
    ``httpx`` rewrites the authority when an unjoined path string
    starts with ``//``, so faithfully reproducing the bypass at the
    ASGI layer requires constructing an ``httpx.URL`` directly
    (SEE-248).
    """
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get(url)
    assert response.status_code == 404, (
        f"expected 404 for {url!r}, got {response.status_code} "
        f"(body starts with {response.text[:40]!r})"
    )


@pytest.mark.parametrize(
    "raw_path",
    ["//api/v1/x", "///api/v1/x", "//api/v1//missing"],
)
def test_collapses_leading_multi_slash_path_at_app_level(
    tmp_path: Path, raw_path: str
) -> None:
    """``CollapseSlashesMiddleware`` rewrites the path before the SPA mount.

    Without the middleware, ``GET //api/v1/x`` reaches the ASGI layer
    with ``scope["path"] == "//api/v1/x"``; Starlette's mount router
    fails to match any route under that path and the SPA fallback
    fires for paths without ``api/`` once the leading runs are stripped
    by the router itself. The middleware collapses the runs upstream
    so ``_is_api_path`` sees the canonical ``/api/v1/x`` and the
    request gets a JSON 404 instead of the HTML SPA index (SEE-248).

    NOTE: ``client.get(raw_path)`` would let ``httpx`` rewrite the
    authority (treating ``//api`` as a network-path reference), so
    construct the URL explicitly to deliver the literal multi-slash
    path through the ASGI scope.
    """
    app = FastAPI()
    app.add_middleware(CollapseSlashesMiddleware)
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    url = httpx.URL("http://testserver" + raw_path)
    response = client.get(url)
    assert response.status_code == 404, (
        f"expected 404 for {raw_path!r}, got {response.status_code} "
        f"(body starts with {response.text[:40]!r})"
    )
    # Body should be JSON 404, not the SPA HTML — confirms the
    # request reached the API/route layer rather than the SPA mount.
    assert "<!doctype html>" not in response.text.lower()


def test_spa_index_sends_no_cache_header(tmp_path: Path) -> None:
    """The SPA shell must not be cached — asset hashes rotate on deploy."""
    app = FastAPI()
    mount_dashboard(app, dist_dir=_write_dist(tmp_path))
    client = TestClient(app)
    response = client.get("/some/client-route")
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "").lower()
