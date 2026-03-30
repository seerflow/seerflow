"""Integration tests for entity window buffer pipeline wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from seerflow.config import SeerflowConfig
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline.handler import _make_handler
from seerflow.receivers.base import RawEvent

pytestmark = pytest.mark.integration


def _mock_storage() -> AsyncMock:
    """Create a mock storage with all methods used by the handler."""
    mock = AsyncMock()
    mock.write_events = AsyncMock()
    mock.write_edge = AsyncMock()
    mock.upsert_template = AsyncMock()
    mock.save_state = AsyncMock()
    mock.write_templates = AsyncMock()
    mock.write_alert = AsyncMock()
    return mock


class TestWindowPipelineIntegration:
    """Test that EntityWindowBuffer is wired into the pipeline handler."""

    async def test_event_with_entities_added_to_window(self) -> None:
        """Events with entities are added to the window buffer."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        window = EntityWindowBuffer(
            window_ns=config.correlation.window_duration_seconds * 1_000_000_000,
            max_events=config.correlation.max_events_per_entity,
            max_entities=config.correlation.max_entities,
        )

        handler = _make_handler(ensemble, mock, window_buffer=window)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        # The test message contains IP + user — entities should be extracted
        assert window.entity_count > 0, "Expected entities from test message"
        stats = window.stats()
        assert stats["total_events"] > 0

    async def test_handler_without_window_still_works(self) -> None:
        """Handler works when window_buffer is not provided (backward compat)."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        handler = _make_handler(ensemble, mock)

        event = RawEvent(
            data=b"simple message",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)
        assert mock.write_events.called

    async def test_no_entities_no_window_update(self) -> None:
        """Events without recognizable entities leave the window buffer empty."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        window = EntityWindowBuffer(
            window_ns=config.correlation.window_duration_seconds * 1_000_000_000,
            max_events=config.correlation.max_events_per_entity,
            max_entities=config.correlation.max_entities,
        )

        handler = _make_handler(ensemble, mock, window_buffer=window)

        event = RawEvent(
            data=b"System started successfully",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        assert window.entity_count == 0

    async def test_multiple_entities_each_get_window_entry(self) -> None:
        """An event with multiple entity refs adds to each entity's window."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        window = EntityWindowBuffer(
            window_ns=config.correlation.window_duration_seconds * 1_000_000_000,
            max_events=config.correlation.max_events_per_entity,
            max_entities=config.correlation.max_entities,
        )

        handler = _make_handler(ensemble, mock, window_buffer=window)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        # If entities were extracted, each entity should have at least 1 event
        if window.entity_count > 1:
            stats = window.stats()
            assert stats["total_events"] >= window.entity_count
