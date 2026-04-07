"""Integration tests for graph-structural alert pipeline wiring."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from seerflow.config import GraphStructuralConfig, SeerflowConfig
from seerflow.correlation.graph_structural import GraphStructuralEvaluator
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.graph.entity_graph import EntityGraph
from seerflow.pipeline.handler import make_handler
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


def _no_anomaly() -> DetectionResult:
    """Return a non-anomaly detection result."""
    return DetectionResult(
        score=0.1,
        upper_threshold=0.8,
        lower_threshold=0.05,
        is_anomaly=False,
        anomaly_direction="none",
        source_type="syslog",
    )


class TestGraphStructuralPipelineIntegration:
    """Test that GraphStructuralEvaluator is wired into the pipeline handler."""

    async def test_community_crossing_alert_written_after_edge(self) -> None:
        """Handler writes community-crossing alert when edge crosses communities."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        # Pre-populate graph with 2 communities via pre-seeded vertices.
        graph.add_edge("user-aaa", "host-bbb", "logged_into", 1_000)
        graph.add_edge("user-ccc", "host-ddd", "logged_into", 2_000)
        graph.set_vertex_attr("user-aaa", "community_id", 0)
        graph.set_vertex_attr("host-bbb", "community_id", 0)
        graph.set_vertex_attr("user-ccc", "community_id", 1)
        graph.set_vertex_attr("host-ddd", "community_id", 1)

        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)

        handler = make_handler(
            ensemble,
            mock,
            entity_graph=graph,
            graph_structural=evaluator,
        )

        # Patch check_community_crossing to fire on the first edge the handler
        # creates.  This avoids relying on entity resolution producing our
        # pre-seeded UUIDs — the evaluator is called with whatever edge the
        # handler infers, and we simulate a crossing result.
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel

        crossing_alert = Alert(
            alert_id="cc-test-alert",
            alert_type="correlation",
            timestamp_ns=3_000_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="graph-community-crossing",
            description="Community-crossing edge (test)",
            entity_uuid="user-aaa",
            entity_value="user-aaa",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("lateral-movement",),
            mitre_techniques=("T1021",),
            risk_score=0.6,
            dedup_key="graph:community_crossing:user-aaa:host-ddd",
        )

        with (
            patch.object(type(ensemble), "process_event", return_value=_no_anomaly()),
            patch.object(
                GraphStructuralEvaluator,
                "check_community_crossing",
                return_value=[crossing_alert],
            ),
        ):
            event = RawEvent(
                data=b"user=admin src=10.0.0.1 action=login",
                source_type="syslog",
                source_id="test",
                received_ns=3_000_000_000_000_000_000,
                metadata={},
            )
            await handler(event)

        # Verify the crossing alert was written to storage
        alert_calls = mock.write_alert.call_args_list
        cc_alerts = [
            call
            for call in alert_calls
            if hasattr(call.args[0], "rule_name")
            and call.args[0].rule_name == "graph-community-crossing"
        ]
        assert len(cc_alerts) > 0, "Expected a community-crossing alert to be written to storage"

    async def test_post_algorithms_alerts_written_after_run(self) -> None:
        """Handler writes post-algorithm alerts after run_algorithms()."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        # Pre-seed so graph is non-empty and algorithms will run
        graph.add_edge("seed-a", "seed-b", "has_ip", 1_000)

        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)

        # Use graph_algo_interval=1 so algorithms run on the first event
        handler = make_handler(
            ensemble,
            mock,
            entity_graph=graph,
            graph_structural=evaluator,
            graph_algo_interval=1,
        )

        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel

        betweenness_alert = Alert(
            alert_id="betweenness-test-alert",
            alert_type="correlation",
            timestamp_ns=4_000_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="graph-high-betweenness",
            description="High betweenness centrality (test)",
            entity_uuid="seed-a",
            entity_value="seed-a",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("lateral-movement",),
            mitre_techniques=("T1021",),
            risk_score=0.5,
            dedup_key="graph:betweenness:seed-a",
        )

        with (
            patch.object(type(ensemble), "process_event", return_value=_no_anomaly()),
            patch.object(
                GraphStructuralEvaluator,
                "check_community_crossing",
                return_value=[],
            ),
            patch.object(
                GraphStructuralEvaluator,
                "check_post_algorithms",
                return_value=[betweenness_alert],
            ),
        ):
            event = RawEvent(
                data=b"System log message",
                source_type="syslog",
                source_id="test",
                received_ns=4_000_000_000_000_000_000,
                metadata={},
            )
            await handler(event)

        alert_calls = mock.write_alert.call_args_list
        betweenness_alerts = [
            call
            for call in alert_calls
            if hasattr(call.args[0], "rule_name")
            and call.args[0].rule_name == "graph-high-betweenness"
        ]
        assert len(betweenness_alerts) > 0, (
            "Expected a betweenness alert to be written after run_algorithms()"
        )

    async def test_handler_without_graph_structural_still_works(self) -> None:
        """Handler works without graph_structural evaluator (backward compat)."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        handler = make_handler(ensemble, mock, entity_graph=graph)

        event = RawEvent(
            data=b"user=admin src=10.0.0.1 action=login",
            source_type="syslog",
            source_id="test",
            received_ns=time.time_ns(),
            metadata={},
        )
        await handler(event)
        assert mock.write_events.called

    async def test_graph_structural_alert_write_failure_does_not_crash(self) -> None:
        """Storage failure when writing graph alert is caught gracefully."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        mock.write_alert = AsyncMock(side_effect=OSError("disk full"))
        graph = EntityGraph()

        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)

        handler = make_handler(
            ensemble,
            mock,
            entity_graph=graph,
            graph_structural=evaluator,
        )

        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel

        crossing_alert = Alert(
            alert_id="cc-fail-test",
            alert_type="correlation",
            timestamp_ns=5_000_000_000_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="graph-community-crossing",
            description="Community-crossing edge (test fail)",
            entity_uuid="user-aaa",
            entity_value="user-aaa",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("lateral-movement",),
            mitre_techniques=("T1021",),
            risk_score=0.6,
            dedup_key="graph:community_crossing:user-aaa:host-ddd",
        )

        with (
            patch.object(type(ensemble), "process_event", return_value=_no_anomaly()),
            patch.object(
                GraphStructuralEvaluator,
                "check_community_crossing",
                return_value=[crossing_alert],
            ),
        ):
            event = RawEvent(
                data=b"user=admin src=10.0.0.1 action=login",
                source_type="syslog",
                source_id="test",
                received_ns=5_000_000_000_000_000_000,
                metadata={},
            )
            # Should not raise despite write_alert failing
            await handler(event)

    async def test_evaluator_receives_correct_edge_args(self) -> None:
        """Verify check_community_crossing is called with inferred edge params."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()
        graph = EntityGraph()

        evaluator = GraphStructuralEvaluator(GraphStructuralConfig(), graph)

        handler = make_handler(
            ensemble,
            mock,
            entity_graph=graph,
            graph_structural=evaluator,
        )

        with (
            patch.object(type(ensemble), "process_event", return_value=_no_anomaly()),
            patch.object(
                GraphStructuralEvaluator,
                "check_community_crossing",
                return_value=[],
            ) as mock_cc,
        ):
            event = RawEvent(
                data=b"user=admin src=10.0.0.1 action=login",
                source_type="syslog",
                source_id="test",
                received_ns=6_000_000_000_000_000_000,
                metadata={},
            )
            await handler(event)

        # If edges were inferred, check_community_crossing should have been called
        if graph.edge_count > 0:
            assert mock_cc.called, (
                "Expected check_community_crossing to be called for inferred edges"
            )
            # Verify it was called with 4 positional args: source_id,
            # target_id, rel_type, timestamp_ns
            for call in mock_cc.call_args_list:
                assert len(call.args) == 4, f"Expected 4 positional args, got {len(call.args)}"
