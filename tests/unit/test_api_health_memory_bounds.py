"""S-082 — verify ``GET /api/v1/health`` surfaces the per-component
memory-bound snapshot under ``memory_bounds``.

The route is exercised end-to-end via ``TestClient`` so the FastAPI
dependency wiring is covered (any silent regression on the new Depends
accessors will surface here, not just at unit level).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.api.routes.health import router
from seerflow.config import DetectionConfig
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent, SeverityLevel


class _StubLogStore:
    """Minimal LogStore stub — health route only touches alert_store."""


class _StubAlertStore:
    async def query_alerts(self, query):  # type: ignore[no-untyped-def]
        from typing import ClassVar

        class _Page:
            total = 0
            items: ClassVar[list[object]] = []

        return _Page()

    async def get_feedback_stats(self) -> dict[str, int]:
        return {}


def _build_app(*, ensemble=None, window_buffer=None) -> FastAPI:
    """Build a bare FastAPI carrying just what the health route reads."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    class _StorageDeps:
        log_store = _StubLogStore()
        alert_store = _StubAlertStore()
        entity_store = None

    class _DetectionEngines:
        sigma_engine = None
        correlation_rules: tuple[object, ...] = ()

    app.state.storage = _StorageDeps()
    engines = _DetectionEngines()
    engines.ensemble = ensemble  # type: ignore[attr-defined]
    app.state.engines = engines
    app.state.health_state = {"pipeline": "running"}
    if window_buffer is not None:
        app.state.window_buffer = window_buffer
    return app


@pytest.mark.unit
def test_health_returns_empty_memory_bounds_on_bare_app() -> None:
    """No audited component wired → ``memory_bounds`` is an empty dict."""
    app = _build_app()
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["memory_bounds"] == {}


@pytest.mark.unit
def test_health_carries_memory_bounds_for_wired_components() -> None:
    """Wire an ensemble + window buffer — the route must surface their
    bounds rows."""
    cfg = DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=16,
    )
    ens = DetectionEnsemble(cfg)
    ens.process_event(
        SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="hello",
            severity_id=SeverityLevel.INFORMATIONAL,
            source_type="syslog",
        )
    )

    window = EntityWindowBuffer(window_ns=10**9, max_events=100, max_entities=64)

    app = _build_app(ensemble=ens, window_buffer=window)
    with TestClient(app) as client:
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    payload = resp.json()
    bounds = payload["memory_bounds"]
    assert "ensemble.sources" in bounds
    assert bounds["ensemble.sources"]["max"] == 16
    assert bounds["ensemble.sources"]["current"] == 1
    assert "correlation.window" in bounds
    assert bounds["correlation.window"]["max"] == 64
    assert bounds["correlation.window"]["current"] == 0
