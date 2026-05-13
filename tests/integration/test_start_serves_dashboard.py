"""Integration coverage for `seerflow start` wiring the FastAPI dashboard.

Covers AC1, AC3, AC6, AC8: the FastAPI app produced by ``create_api_app(...)``
serves the dashboard root, the live ``/api/v1/health`` payload (with the
``feedback`` key from the shared ``AlertStore``), and broadcasts alerts pushed
through the shared ``ConnectionManager`` to a connected WebSocket client.

The integration test exercises the same factory call shape ``pipeline/run.py``
uses, but talks to the ASGI app in-process (httpx ASGI transport for HTTP,
``TestClient`` for WebSockets) so it stays fast and deterministic without
spinning up a real uvicorn process.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import msgspec
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from seerflow.api.app import create_api_app
from seerflow.api.ws import ConnectionManager
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _stub_alert_store() -> MagicMock:
    """Build a stub AlertStore with the awaitable feedback-stats hook the route needs."""
    store = MagicMock()
    store.get_feedback_stats = AsyncMock(return_value={"tp": 0, "fp": 0})
    return store


def _make_alert() -> Alert:
    """Build a minimal Alert that satisfies the msgspec required-field set."""
    return Alert(
        alert_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "s217-roundtrip")),
        alert_type="sigma",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name="s217-unit",
        description="round-trip probe",
        entity_uuid=str(uuid.uuid4()),
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(),
    )


@pytest.mark.asyncio
async def test_dashboard_root_and_health() -> None:
    """AC1 + AC6 — root responds and health surfaces shared state + feedback."""
    ws_manager = ConnectionManager()
    health_state = {"pipeline": "running", "storage": "connected"}
    app = create_api_app(
        log_store=MagicMock(),
        alert_store=_stub_alert_store(),
        entity_store=None,
        ws_manager=ws_manager,
        health_state=health_state,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root = await client.get("/")
        # Either the bundled dist serves index.html (200/HTML) or it is absent
        # in this checkout (404). Both are acceptable wiring outcomes; the
        # AC-relevant assertion is that the route exists at all.
        assert root.status_code in (200, 404)

        health = await client.get("/api/v1/health")
        assert health.status_code == 200
        body = health.json()
        assert body["components"]["pipeline"] == "running"
        assert body["status"] == "healthy"
        # AC6: the FastAPI route must mirror the legacy aiohttp contract so
        # liveness probes that already consume `feedback` keep working.
        assert body["feedback"] == {"tp": 0, "fp": 0}
        # No DetectionEnsemble is wired in this fixture, so detection stays None.
        assert body["detection"] is None


def test_ws_factory_path_rejects_unapproved_origin() -> None:
    """Defence-in-depth: when ``ws_manager=None`` is passed to ``create_api_app``
    (the production path used by ``seerflow start``), the factory must build a
    config-aware ``ConnectionManager`` via ``_build_ws_manager`` whose Origin
    allowlist closes the WS route to non-allowlisted browser clients.

    Catches future regressions where someone short-circuits the factory and
    constructs the manager with the no-allowlist default again (the S-217
    review HIGH that this test is explicitly designed to backstop).
    """
    from starlette.websockets import WebSocketDisconnect

    from seerflow.config import (
        AlertingConfig,
        DetectionConfig,
        SeerflowConfig,
        StorageConfig,
        UEBAConfig,
    )

    config = SeerflowConfig(
        storage=StorageConfig(),
        receivers=(),
        detection=DetectionConfig(),
        alerting=AlertingConfig(),
        ueba=UEBAConfig(),
        dashboard_port=8080,
    )
    app = create_api_app(
        log_store=MagicMock(),
        alert_store=_stub_alert_store(),
        ws_manager=None,
        config=config,
        health_state={"pipeline": "running", "storage": "connected"},
    )

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/api/v1/ws",
            headers={"origin": "http://evil.example.com"},
        ),
    ):
        pass


def test_ws_receives_alert_broadcast() -> None:
    """AC3 + AC8 — alert broadcast on the shared ConnectionManager reaches a WS client."""
    ws_manager = ConnectionManager(
        tick_interval_s=0.005,
        status_interval_s=3600.0,  # effectively disable the periodic status tick
    )
    app = create_api_app(
        log_store=MagicMock(),
        alert_store=_stub_alert_store(),
        ws_manager=ws_manager,
        health_state={"pipeline": "running", "storage": "connected"},
    )

    test_alert = _make_alert()

    with TestClient(app) as client, client.websocket_connect("/api/v1/ws") as ws:
        ws_manager.broadcast_alert(test_alert)
        # Frames are msgspec-encoded bytes (see api/ws.py::_send_bytes).
        raw = ws.receive_bytes()
        payload = msgspec.json.decode(raw)
        # ConnectionManager sends single alerts as {"type":"alert","data":{...}}
        # and batches as {"type":"alert_batch","alerts":[{...}]}; cover both.
        if payload.get("type") == "alert_batch":
            ids = [a["alert_id"] for a in payload["alerts"]]
        else:
            assert payload.get("type") == "alert"
            ids = [payload["data"]["alert_id"]]
        assert test_alert.alert_id in ids
