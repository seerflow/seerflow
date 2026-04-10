"""Tests for pipeline handler ws_manager integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.api.ws import ConnectionManager
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent


@pytest.mark.asyncio
async def test_handler_broadcasts_event_to_ws_manager() -> None:
    ws_manager = MagicMock(spec=ConnectionManager)
    ws_manager.broadcast_event = MagicMock()
    ws_manager.broadcast_alert = MagicMock()

    ensemble = MagicMock(spec=DetectionEnsemble)
    ensemble.process_event = MagicMock(
        return_value=DetectionResult(
            score=0.1,
            upper_threshold=0.9,
            lower_threshold=0.0,
            is_anomaly=False,
            source_type="syslog",
            anomaly_direction=None,
        )
    )

    storage = AsyncMock()
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()

    handler = make_handler(ensemble, storage, ws_manager=ws_manager)
    raw = RawEvent(
        source_id="syslog",
        source_type="syslog",
        received_ns=1_800_000_000_000_000_000,
        data=b"test message",
        metadata={},
    )
    await handler(raw)

    assert ws_manager.broadcast_event.call_count == 1
    ws_manager.broadcast_alert.assert_not_called()


@pytest.mark.asyncio
async def test_handler_without_ws_manager_does_not_broadcast() -> None:
    ensemble = MagicMock(spec=DetectionEnsemble)
    ensemble.process_event = MagicMock(
        return_value=DetectionResult(
            score=0.1,
            upper_threshold=0.9,
            lower_threshold=0.0,
            is_anomaly=False,
            source_type="syslog",
            anomaly_direction=None,
        )
    )

    storage = AsyncMock()
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()

    handler = make_handler(ensemble, storage)  # ws_manager=None default
    raw = RawEvent(
        source_id="syslog",
        source_type="syslog",
        received_ns=1_800_000_000_000_000_000,
        data=b"test message",
        metadata={},
    )
    await handler(raw)  # Must not raise


@pytest.mark.asyncio
async def test_handler_broadcasts_ml_alert_on_anomaly() -> None:
    ws_manager = MagicMock(spec=ConnectionManager)
    ws_manager.broadcast_event = MagicMock()
    ws_manager.broadcast_alert = MagicMock()

    ensemble = MagicMock(spec=DetectionEnsemble)
    ensemble.process_event = MagicMock(
        return_value=DetectionResult(
            score=0.95,
            upper_threshold=0.5,
            lower_threshold=0.0,
            is_anomaly=True,
            source_type="syslog",
            anomaly_direction="upper",
        )
    )

    storage = AsyncMock()
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_alert = AsyncMock(return_value=True)  # is_new = True

    handler = make_handler(ensemble, storage, ws_manager=ws_manager)
    raw = RawEvent(
        source_id="syslog",
        source_type="syslog",
        received_ns=1_800_000_000_000_000_000,
        data=b"suspicious activity detected from 10.0.0.1",
        metadata={},
    )
    await handler(raw)

    assert ws_manager.broadcast_alert.call_count >= 1


@pytest.mark.asyncio
async def test_handler_does_not_broadcast_deduped_alert() -> None:
    ws_manager = MagicMock(spec=ConnectionManager)
    ws_manager.broadcast_event = MagicMock()
    ws_manager.broadcast_alert = MagicMock()

    ensemble = MagicMock(spec=DetectionEnsemble)
    ensemble.process_event = MagicMock(
        return_value=DetectionResult(
            score=0.95,
            upper_threshold=0.5,
            lower_threshold=0.0,
            is_anomaly=True,
            source_type="syslog",
            anomaly_direction="upper",
        )
    )

    storage = AsyncMock()
    storage.write_events = AsyncMock()
    storage.write_templates = AsyncMock()
    storage.write_alert = AsyncMock(return_value=False)  # deduped

    handler = make_handler(ensemble, storage, ws_manager=ws_manager)
    raw = RawEvent(
        source_id="syslog",
        source_type="syslog",
        received_ns=1_800_000_000_000_000_000,
        data=b"repeated event from 10.0.0.1",
        metadata={},
    )
    await handler(raw)

    ws_manager.broadcast_alert.assert_not_called()
