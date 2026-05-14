"""Verify that ``GET /api/v1/stats`` redacts DSN-bearing exceptions in logs.

S-056 code review flagged that ``_log.warning("...", exc_info=True)`` lets
``asyncpg``-style DSN leakage reach log handlers. S-080 swaps those sites
to ``sanitize_exception``-formatted messages. These tests pin the
contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.deps import StorageDeps
from seerflow.api.routes.stats import router

if TYPE_CHECKING:
    from seerflow.api.metrics import PipelineMetrics


@pytest.fixture
def app_with_dsn_failures() -> tuple[FastAPI, MagicMock, MagicMock]:
    """Build a minimal app whose alert store and metrics provider both raise."""
    app = FastAPI()
    app.state.config = None
    log_store = MagicMock()
    page = MagicMock()
    page.total = 0
    log_store.query_events = AsyncMock(return_value=page)
    alert_store = MagicMock()
    alert_store.query_alerts = AsyncMock(return_value=page)
    alert_store.get_feedback_stats = AsyncMock(return_value={})
    alert_store.count_by_severity = AsyncMock(
        side_effect=RuntimeError("postgresql://user:LEAKED_PASSWORD@db.example.com:5432/seer")
    )
    app.state.storage = StorageDeps(log_store=log_store, alert_store=alert_store)

    def _bad_metrics() -> PipelineMetrics:
        raise RuntimeError("metrics fail dsn=postgresql://u:METRICS_PW@h/d")

    app.state.pipeline_metrics_provider = _bad_metrics
    app.include_router(router, prefix="/api/v1")
    return app, alert_store, app.state.pipeline_metrics_provider


class TestStatsRouteLogRedaction:
    """Both failing paths in /stats must scrub credentials before logging."""

    @staticmethod
    def _format_records(records: list[logging.LogRecord]) -> str:
        """Render each record the way a handler would (message + traceback)."""
        formatter = logging.Formatter("%(message)s")
        return "\n".join(formatter.format(r) for r in records)

    def test_count_by_severity_failure_redacts_dsn(
        self,
        app_with_dsn_failures: tuple[FastAPI, MagicMock, MagicMock],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app, _alert_store, _provider = app_with_dsn_failures
        with caplog.at_level(logging.WARNING, logger="seerflow.api.stats"):
            client = TestClient(app)
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        rendered = self._format_records(caplog.records)
        # No record (message or exc_info traceback) may carry the password.
        assert "LEAKED_PASSWORD" not in rendered
        # And we must not have attached exc_info — that would leak the DSN
        # via the traceback regardless of the sanitized message.
        for record in caplog.records:
            if "count_by_severity" in record.getMessage() or "severity" in record.getMessage():
                assert record.exc_info is None, (
                    "stats route still passes exc_info=True; DSN can leak via traceback"
                )

    def test_metrics_provider_failure_redacts_dsn(
        self,
        app_with_dsn_failures: tuple[FastAPI, MagicMock, MagicMock],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app, _alert_store, _provider = app_with_dsn_failures
        with caplog.at_level(logging.WARNING, logger="seerflow.api.stats"):
            client = TestClient(app)
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        rendered = self._format_records(caplog.records)
        assert "METRICS_PW" not in rendered
        for record in caplog.records:
            if "metrics" in record.getMessage():
                assert record.exc_info is None, (
                    "stats route still passes exc_info=True; DSN can leak via traceback"
                )
