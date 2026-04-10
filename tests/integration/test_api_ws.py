"""Integration test: WebSocket streaming with real FastAPI app and ConnectionManager."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from fastapi.testclient import TestClient

from seerflow.api.app import create_api_app
from seerflow.api.ws import ConnectionManager
from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent
from seerflow.storage.sqlite import SqliteBackend


@pytest.fixture
async def backend(tmp_path: Path) -> SqliteBackend:
    db_path = str(tmp_path / "test_ws.db")
    config = StorageConfig(backend="sqlite", sqlite_path=db_path)
    b = await SqliteBackend.connect(config)
    yield b  # type: ignore[misc]
    await b.close()


@pytest.fixture
def ws_manager() -> ConnectionManager:
    return ConnectionManager(
        tick_interval_s=0.005,
        status_interval_s=3600.0,  # effectively disabled for tests
    )


@pytest.fixture
def client(backend: SqliteBackend, ws_manager: ConnectionManager) -> TestClient:
    app = create_api_app(
        log_store=backend,
        alert_store=backend,
        ws_manager=ws_manager,
    )
    return TestClient(app)


def _make_event(source_type: str = "syslog", severity_id: int = 3) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_800_000_000_000_000_000,
        observed_ns=1_800_000_000_000_000_001,
        message="integration test event",
        source_type=source_type,
        severity_id=severity_id,  # type: ignore[arg-type]
    )


def _make_alert(alert_type: str = "sigma") -> Alert:
    return Alert(
        alert_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"int-{alert_type}")),
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_800_000_000_000_000_000,
        severity_id=4,  # type: ignore[arg-type]
        rule_name="integration-rule",
        description="integration alert",
        entity_uuid=str(uuid.uuid4()),
        entity_value="10.0.0.99",
        entity_type="ip",
        contributing_events=(),
    )


class TestWebSocketIntegration:
    def test_connect_and_receive_event(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        with client.websocket_connect("/api/v1/ws") as ws:
            ws_manager.broadcast_event(_make_event())
            msg = ws.receive_json()
            assert msg["type"] == "event"
            assert msg["data"]["source_type"] == "syslog"

    def test_filter_suppresses_non_matching_event(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        import time as _t

        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "filter", "min_severity": 4})
            # Give the ASGI server loop time to apply the filter before broadcast
            _t.sleep(0.05)
            ws_manager.broadcast_event(_make_event(severity_id=2))
            ws_manager.broadcast_event(_make_event(severity_id=5))
            msg = ws.receive_json()
            assert msg["type"] == "event"
            assert msg["data"]["severity_id"] == 5

    def test_receive_alert(self, client: TestClient, ws_manager: ConnectionManager) -> None:
        with client.websocket_connect("/api/v1/ws") as ws:
            ws_manager.broadcast_alert(_make_alert())
            msg = ws.receive_json()
            assert msg["type"] == "alert"
            assert msg["data"]["alert_type"] == "sigma"

    def test_bad_filter_returns_error(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "filter", "alert_types": ["not-a-real-type"]})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "not-a-real-type" in msg["message"]

    def test_disconnect_removes_client(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        with client.websocket_connect("/api/v1/ws"):
            assert ws_manager.connected_count == 1
        # After context manager exits, a small yield is needed for disconnect
        import time as _t

        _t.sleep(0.05)
        assert ws_manager.connected_count == 0

    def test_non_dict_message_is_ignored(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        """Route must tolerate non-dict JSON payloads without crashing."""
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json(["not", "a", "dict"])
            # Broadcast an event and confirm we still receive it — connection is alive
            ws_manager.broadcast_event(_make_event())
            msg = ws.receive_json()
            assert msg["type"] == "event"

    def test_non_filter_message_is_ignored(
        self, client: TestClient, ws_manager: ConnectionManager
    ) -> None:
        """Route must ignore client messages with unknown ``type`` values."""
        with client.websocket_connect("/api/v1/ws") as ws:
            ws.send_json({"type": "subscribe", "topic": "foo"})
            ws_manager.broadcast_event(_make_event())
            msg = ws.receive_json()
            assert msg["type"] == "event"

    def test_startup_and_shutdown_hooks_exercised(
        self, backend: SqliteBackend
    ) -> None:
        """Using ``with TestClient(app)`` triggers the startup/shutdown lifespan."""
        app = create_api_app(log_store=backend, alert_store=backend)
        with TestClient(app):
            # Lifespan startup has fired; ws_manager status task is running
            mgr = app.state.ws_manager
            assert mgr is not None
            assert mgr._status_task is not None
        # After exit, shutdown hook has fired — status task is done
        assert app.state.ws_manager._status_task is None or app.state.ws_manager._status_task.done()
