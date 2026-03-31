"""Integration tests for risk accumulation pipeline wiring."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from seerflow.config import SeerflowConfig
from seerflow.correlation.holders import EngineHolder
from seerflow.correlation.risk import RiskRegister
from seerflow.detection.ensemble import DetectionEnsemble, DetectionResult
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


class TestRiskPipelineIntegration:
    """Test that RiskRegister is wired into the pipeline handler."""

    async def test_ml_anomaly_adds_risk_to_entities(self) -> None:
        """ML anomaly detection adds risk entries to the register."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        risk_register = RiskRegister(
            half_life_ns=config.detection.risk_half_life_hours * 3600 * 1_000_000_000,
            threshold=config.detection.risk_threshold,
            max_entities=config.detection.risk_max_entities,
        )

        handler = _make_handler(ensemble, mock, risk_register=risk_register)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=time.time_ns(),
            metadata={},
        )

        # Patch ensemble to return an anomaly
        fake_result = DetectionResult(
            score=0.95,
            upper_threshold=0.5,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        with patch.object(type(ensemble), "process_event", return_value=fake_result):
            await handler(event)

        # Risk should have been added for detected entities
        assert risk_register.entity_count > 0, "Expected entities in risk register"
        assert mock.write_alert.called, "Expected ML alert to be written"

    async def test_sigma_match_adds_risk_to_entities(self) -> None:
        """Sigma rule matches add risk entries to the register."""
        from seerflow.models.alert import Alert
        from seerflow.models.event import SeverityLevel
        from seerflow.sigma.engine import SigmaEngine

        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        risk_register = RiskRegister(
            half_life_ns=config.detection.risk_half_life_hours * 3600 * 1_000_000_000,
            threshold=config.detection.risk_threshold,
            max_entities=config.detection.risk_max_entities,
        )

        sigma_engine = SigmaEngine()

        handler = _make_handler(
            ensemble,
            mock,
            risk_register=risk_register,
            sigma_holder=EngineHolder(engine=sigma_engine),
        )

        event = RawEvent(
            data=b"Failed password for root from 10.0.0.1 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=time.time_ns(),
            metadata={},
        )

        # Patch sigma engine to return a matching alert
        fake_sigma_alert = Alert(
            alert_id="sigma-test-alert",
            alert_type="sigma",
            timestamp_ns=time.time_ns(),
            severity_id=SeverityLevel.CRITICAL,
            rule_name="test-sigma-rule",
            description="Test sigma match",
            entity_uuid="test-entity-uuid",
            entity_value="10.0.0.1",
            entity_type="ip",
            contributing_events=(),
            mitre_tactics=("TA0001",),
            mitre_techniques=("T1078",),
            dedup_key="sigma:test:syslog",
        )
        with (
            patch.object(type(sigma_engine), "evaluate", return_value=[fake_sigma_alert]),
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
            await handler(event)

        # Risk should have been added from sigma match
        assert risk_register.entity_count > 0, "Expected entities in risk register from sigma"

    async def test_handler_without_risk_register_still_works(self) -> None:
        """Handler works when no risk register is provided (backward compat)."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        # No risk_register passed — should not error
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

    async def test_risk_threshold_fires_correlation_alert(self) -> None:
        """When risk exceeds threshold, a correlation alert is written."""
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        mock = _mock_storage()

        # Use a very low threshold so a single high-score anomaly triggers it
        risk_register = RiskRegister(
            half_life_ns=config.detection.risk_half_life_hours * 3600 * 1_000_000_000,
            threshold=1.0,  # Very low — one anomaly should exceed this
            max_entities=config.detection.risk_max_entities,
        )

        handler = _make_handler(ensemble, mock, risk_register=risk_register)

        event = RawEvent(
            data=b"Failed password for root from 192.168.1.100 port 22 ssh2",
            source_type="syslog",
            source_id="test",
            received_ns=time.time_ns(),
            metadata={},
        )

        fake_result = DetectionResult(
            score=0.95,
            upper_threshold=0.5,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        with patch.object(type(ensemble), "process_event", return_value=fake_result):
            await handler(event)

        # With threshold=1.0 and score=0.95*10=9.5 risk points,
        # the threshold should be exceeded, triggering a correlation alert
        alert_calls = mock.write_alert.call_args_list
        correlation_alerts = [
            call
            for call in alert_calls
            if hasattr(call.args[0], "alert_type") and call.args[0].alert_type == "correlation"
        ]
        assert len(correlation_alerts) > 0, (
            "Expected a correlation alert when risk threshold exceeded"
        )
