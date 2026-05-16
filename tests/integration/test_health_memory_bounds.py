"""S-082 integration tests — end-to-end ``/api/v1/health`` carries the
``memory_bounds`` envelope when audited components are wired.

The setup keeps the FastAPI app minimal but wires real ``DetectionEnsemble``
+ ``EntityWindowBuffer`` instances directly onto ``app.state`` so the
audit aggregator actually has bounds to surface. The route's defensive
``getattr`` fallback path is exercised by the bare-app test in the unit
suite.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.config import DetectionConfig
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent, SeverityLevel

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
def bounded_client(backend: SqliteBackend) -> TestClient:
    """Wire an ensemble + window buffer onto ``app.state`` so the health
    route's S-082 ``memory_bounds`` field is populated.
    """
    cfg = DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=32,
    )
    ens = DetectionEnsemble(cfg)
    # Warm one source so ``ensemble.sources.current`` is ``1`` (rather
    # than ``0``) — proves the aggregator is reading live state.
    ens.process_event(
        SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="warm",
            severity_id=SeverityLevel.INFORMATIONAL,
            source_type="syslog",
        )
    )

    window = EntityWindowBuffer(window_ns=10**9, max_events=100, max_entities=128)

    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        health_state={"pipeline": "running", "storage.sqlite": "connected"},
        ensemble=ens,
    )
    app.state.window_buffer = window
    return TestClient(app)


def test_health_envelope_carries_memory_bounds(bounded_client: TestClient) -> None:
    resp = bounded_client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "memory_bounds" in body
    bounds = body["memory_bounds"]

    # Ensemble rows (sources, template_hw, entity_hw, markov) must all be
    # present because the ensemble is wired.
    expected = (
        "ensemble.sources",
        "ensemble.template_hw",
        "ensemble.entity_hw",
        "ensemble.markov",
    )
    for key in expected:
        assert key in bounds, f"missing {key} in memory_bounds"
        assert set(bounds[key]) == {"current", "max", "evictions"}

    assert bounds["ensemble.sources"]["current"] == 1
    assert bounds["ensemble.sources"]["max"] == 32

    # Window buffer surfaces under its audit key.
    assert "correlation.window" in bounds
    assert bounds["correlation.window"]["max"] == 128


def test_health_under_50ms_with_bounds(bounded_client: TestClient) -> None:
    """FR-047: the audit collection must not blow the 50 ms budget.

    S-233: assert on the route's *own* processing duration
    (``X-Process-Time-Ms``) rather than the client round-trip wall clock.
    The round-trip measurement transiently exceeds 50 ms under full-suite
    parallel + coverage load purely from OS scheduler latency in the test
    process, not endpoint work; the server-side value is immune to that
    while still genuinely guarding the endpoint (coverage still instruments
    the route code, so the measurement is, if anything, conservative).
    """
    # Warm-up call (first request pays one-time import / cache priming).
    bounded_client.get("/api/v1/health")

    server_ms_max = 0.0
    for _ in range(10):
        resp = bounded_client.get("/api/v1/health")
        assert resp.status_code == 200
        server_ms = float(resp.headers["x-process-time-ms"])
        server_ms_max = max(server_ms_max, server_ms)

    assert server_ms_max < 50.0, (
        f"max server-side health processing {server_ms_max:.1f}ms exceeds "
        f"the FR-047 50 ms budget"
    )
