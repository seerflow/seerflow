"""Integration tests for AlertDispatcher wired into the pipeline handler.

Tests the full path: RawEvent → handler → write_alert → enqueue → dispatcher → HTTP POST.
Uses aiohttp.test_utils.TestServer as a local webhook endpoint so the real
aiohttp.ClientSession.post() path is exercised without external network calls.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from seerflow.config import StorageConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.receivers.base import RawEvent
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(message: str, source_type: str = "syslog") -> RawEvent:
    """Build a RawEvent from a log message (mirrors test_e2e_pipeline)."""
    return RawEvent(
        data=message.encode(),
        source_type=source_type,
        source_id=f"{source_type}-test",
        received_ns=time.time_ns(),
        metadata={},
    )


def _make_alert(
    *,
    severity_id: SeverityLevel = SeverityLevel.CRITICAL,
    rule_name: str = "test-rule",
) -> Alert:
    """Build a fully-populated Alert for direct dispatcher enqueue tests."""
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=time.time_ns(),
        severity_id=severity_id,
        rule_name=rule_name,
        description="Integration test alert",
        entity_uuid=str(uuid.uuid4()),
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(uuid.uuid4(),),
        risk_score=0.8,
        dedup_key=f"test:{rule_name}",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def webhook_server() -> AsyncIterator[tuple[str, list[dict[str, object]]]]:
    """Start a local aiohttp TestServer that records POST payloads."""
    received: list[dict[str, object]] = []

    async def _handler(request: web.Request) -> web.Response:
        body = await request.json()
        received.append(body)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/webhook", _handler)
    server = TestServer(app)
    await server.start_server()
    url = f"http://{server.host}:{server.port}/webhook"
    try:
        yield url, received
    finally:
        await server.close()


@pytest.fixture()
async def storage(tmp_path: Path) -> AsyncIterator[SqliteBackend]:
    """Create a real SqliteBackend in a tmp path for integration tests."""
    cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "webhook.db"))
    backend = await SqliteBackend.connect(cfg)
    try:
        yield backend
    finally:
        await backend.close()
