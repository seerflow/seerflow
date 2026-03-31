"""Integration tests for correlation engine pipeline wiring."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from seerflow.config import SeerflowConfig
from seerflow.correlation.engine import CorrelationEngine
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
from seerflow.models.alert import CorrelationRule, SourceCondition
from seerflow.models.event import SeverityLevel
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


def _make_rule() -> CorrelationRule:
    return CorrelationRule(
        name="test_brute_force",
        entity_type="ip",
        window_seconds=1800,
        sources=(
            SourceCondition(
                source_type="syslog",
                conditions={"message": "Failed password.*"},
                min_count=2,
            ),
        ),
        min_sources=1,
        alert_severity=SeverityLevel.WARNING,
    )


class TestCorrelationEnginePipelineIntegration:
    """Test that CorrelationEngine is wired into the pipeline handler."""

    async def test_correlation_engine_fires_alert_on_match(self) -> None:
        """Handler evaluates correlation rules and writes alerts when fired."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        window = EntityWindowBuffer(
            window_ns=1800 * 1_000_000_000,
            max_events=1000,
            max_entities=10_000,
        )
        rule = _make_rule()
        engine = CorrelationEngine(rules=[rule], window=window)

        handler = _make_handler(
            ensemble,
            mock,
            window_buffer=window,
            correlation_engine=engine,
        )

        # Patch ensemble to return a non-anomaly so only correlation fires
        non_anomaly = DetectionResult(
            score=0.1,
            upper_threshold=0.5,
            lower_threshold=0.1,
            is_anomaly=False,
            anomaly_direction=None,
            source_type="syslog",
        )

        # Send multiple events with the same entity to trigger correlation
        # (min_count=2 in the rule, so we need at least 2 matching events)
        with patch.object(type(ensemble), "process_event", return_value=non_anomaly):
            for _i in range(3):
                event = RawEvent(
                    data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
                    source_type="syslog",
                    source_id="test",
                    received_ns=time.time_ns(),
                    metadata={},
                )
                await handler(event)

        # At least one correlation alert should have been written
        # (the 2nd and 3rd events should each trigger the rule since window has >=2 matches)
        alert_calls = mock.write_alert.call_args_list
        correlation_alerts = [
            call
            for call in alert_calls
            if hasattr(call.args[0], "alert_type") and call.args[0].alert_type == "correlation"
        ]
        assert len(correlation_alerts) > 0, (
            "Expected at least one correlation alert when rule conditions met"
        )

    async def test_handler_without_correlation_engine_still_works(self) -> None:
        """Handler works when no correlation engine is provided (backward compat)."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        # No correlation_engine passed — should not error
        handler = _make_handler(ensemble, mock)

        event = RawEvent(
            data=b"simple message",
            source_type="syslog",
            source_id="test",
            received_ns=time.time_ns(),
            metadata={},
        )
        await handler(event)
        assert mock.write_events.called

    async def test_correlation_engine_exception_does_not_crash_handler(self) -> None:
        """If correlation engine raises, handler logs warning and continues."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        window = EntityWindowBuffer(
            window_ns=1800 * 1_000_000_000,
            max_events=1000,
            max_entities=10_000,
        )
        rule = _make_rule()
        engine = CorrelationEngine(rules=[rule], window=window)

        handler = _make_handler(
            ensemble,
            mock,
            window_buffer=window,
            correlation_engine=engine,
        )

        # Patch engine.evaluate at the class level (CorrelationEngine uses __slots__)
        with (
            patch.object(type(engine), "evaluate", side_effect=RuntimeError("boom")),
            patch.object(
                type(ensemble),
                "process_event",
                return_value=DetectionResult(
                    score=0.1,
                    upper_threshold=0.5,
                    lower_threshold=0.1,
                    is_anomaly=False,
                    anomaly_direction=None,
                    source_type="syslog",
                ),
            ),
        ):
            event = RawEvent(
                data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
                source_type="syslog",
                source_id="test",
                received_ns=time.time_ns(),
                metadata={},
            )
            # Should NOT raise — handler catches correlation errors
            await handler(event)

        # Events should still be persisted despite correlation failure
        assert mock.write_events.called

    async def test_correlation_alert_write_failure_does_not_crash_handler(self) -> None:
        """If storage.write_alert fails for a correlation alert, handler continues."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        # Make write_alert fail
        mock.write_alert = AsyncMock(side_effect=RuntimeError("storage down"))

        window = EntityWindowBuffer(
            window_ns=1800 * 1_000_000_000,
            max_events=1000,
            max_entities=10_000,
        )
        rule = _make_rule()
        engine = CorrelationEngine(rules=[rule], window=window)

        handler = _make_handler(
            ensemble,
            mock,
            window_buffer=window,
            correlation_engine=engine,
        )

        non_anomaly = DetectionResult(
            score=0.1,
            upper_threshold=0.5,
            lower_threshold=0.1,
            is_anomaly=False,
            anomaly_direction=None,
            source_type="syslog",
        )

        # Send enough events to trigger the correlation rule
        with patch.object(type(ensemble), "process_event", return_value=non_anomaly):
            for _i in range(3):
                event = RawEvent(
                    data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
                    source_type="syslog",
                    source_id="test",
                    received_ns=time.time_ns(),
                    metadata={},
                )
                # Should NOT raise even though write_alert fails
                await handler(event)

        # Events should still be persisted
        assert mock.write_events.called
