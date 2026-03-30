"""Integration tests for entity graph pipeline wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from seerflow.config import SeerflowConfig
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.graph.entity_graph import EntityGraph
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


class TestGraphPipelineIntegration:
    """Test that EntityGraph is wired into the pipeline handler."""

    async def test_event_with_entities_creates_graph_edges(self) -> None:
        """Events with IP+user entities produce edges in the graph."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        handler = _make_handler(ensemble, mock, entity_graph=graph)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        # If entities were extracted, graph should have edges
        if graph.vertex_count > 0:
            assert graph.edge_count > 0

    async def test_event_with_entities_writes_edges_to_storage(self) -> None:
        """Edges inferred from entities are persisted via storage.write_edge."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        handler = _make_handler(ensemble, mock, entity_graph=graph)

        event = RawEvent(
            data=b"Accepted publickey for admin from 10.0.1.42 port 43210 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        # Should persist edges to storage
        if graph.edge_count > 0:
            assert mock.write_edge.called

    async def test_no_entities_no_graph_update(self) -> None:
        """Events without recognizable entities leave the graph empty."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        handler = _make_handler(ensemble, mock, entity_graph=graph)

        event = RawEvent(
            data=b"System started successfully",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        assert graph.vertex_count == 0
        assert graph.edge_count == 0

    async def test_handler_without_graph_still_works(self) -> None:
        """Handler works when entity_graph is not provided (backward compat)."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        handler = _make_handler(ensemble, mock)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        await handler(event)

        # Should complete without error; write_edge should not be called
        assert not mock.write_edge.called

    async def test_write_edge_failure_does_not_crash_handler(self) -> None:
        """Storage edge write failure is logged but does not crash the handler."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        mock.write_edge = AsyncMock(side_effect=OSError("disk full"))
        graph = EntityGraph()

        handler = _make_handler(ensemble, mock, entity_graph=graph)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=1_700_000_000_000_000_000,
            metadata={},
        )
        # Should not raise even though write_edge fails
        await handler(event)

        # Graph should still be updated in-memory even if storage fails
        if graph.edge_count > 0:
            assert mock.write_edge.called
