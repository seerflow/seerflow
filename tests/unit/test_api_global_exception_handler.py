"""Unit tests for the FastAPI catch-all exception handler (S-080).

S-052 review noted that ``create_api_app`` had no
``@app.exception_handler(Exception)``: any unhandled storage failure
(SQLite locked, asyncpg connection drop) produced a raw Starlette 500 with
the exception's ``repr`` in the body, leaking implementation details.
S-080 installs a sanitized handler.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app

if TYPE_CHECKING:
    import pytest


def _build_app() -> tuple[object, MagicMock, MagicMock]:
    """Build a real ``create_api_app`` with mock stores and inject test routes."""
    log_store = MagicMock()
    alert_store = MagicMock()
    app = create_api_app(log_store=log_store, alert_store=alert_store)

    @app.get("/api/v1/_test/boom")
    def _boom() -> dict[str, str]:
        raise RuntimeError("postgresql://user:LEAKED_PW@h/d went bad")

    @app.get("/api/v1/_test/http404")
    def _http404() -> dict[str, str]:
        raise HTTPException(status_code=404, detail="missing")

    return app, log_store, alert_store


class TestGlobalExceptionHandler:
    """Behaviour of the new catch-all handler."""

    def test_unhandled_exception_returns_500_with_safe_body(self) -> None:
        app, _, _ = _build_app()
        # TestClient(..., raise_server_exceptions=False) lets Starlette's
        # exception handler convert the raised RuntimeError into a 500
        # response we can inspect (default would re-raise into pytest).
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/_test/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body == {"detail": "Internal server error"}
        # Never leak repr or DSN into the wire body.
        assert "LEAKED_PW" not in resp.text
        assert "postgresql://" not in resp.text

    def test_unhandled_exception_is_logged_with_sanitized_message(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app, _, _ = _build_app()
        client = TestClient(app, raise_server_exceptions=False)
        with caplog.at_level(logging.ERROR):
            client.get("/api/v1/_test/boom")
        rendered = "\n".join(r.getMessage() for r in caplog.records)
        assert "LEAKED_PW" not in rendered
        assert "unhandled" in rendered.lower() or "internal" in rendered.lower()

    def test_http_exceptions_still_pass_through(self) -> None:
        app, _, _ = _build_app()
        client = TestClient(app)
        resp = client.get("/api/v1/_test/http404")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "missing"}
