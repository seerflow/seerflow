"""Unit tests for IoCAlertBuilder.build_alert (S-069)."""

from __future__ import annotations

import time
import uuid

import pytest

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.indicator import Indicator
from seerflow.models.ioc_match import IoCMatch
from seerflow.threat_intel.enricher import IoCAlertBuilder


def _evt() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type="syslog",
        message="conn from 1.2.3.4",
        related_ips=("1.2.3.4",),
    )


def _match(event_id: str, *, confidence: int = 75) -> IoCMatch:
    return IoCMatch(
        value="1.2.3.4",
        type="ipv4",
        indicator=Indicator(
            value="1.2.3.4",
            type="ipv4",
            source_feed="alienvault-otx",
            confidence=confidence,
            kill_chain_phases=("command-and-control",),
            valid_from_ns=0,
            valid_until_ns=None,
        ),
        event_id=event_id,
        entity_kind="ip",
        matched_at_ns=time.time_ns(),
    )


@pytest.mark.unit
class TestBuildAlert:
    def test_populates_every_alert_field(self) -> None:
        e = _evt()
        m = _match(str(e.event_id))
        alert = IoCAlertBuilder().build_alert(
            m, e, entity_uuid="u-1", entity_value="1.2.3.4", entity_type="ip"
        )
        assert alert.alert_type == "ioc"
        assert alert.rule_name == "ti:alienvault-otx"
        assert "1.2.3.4" in alert.description
        assert "alienvault-otx" in alert.description
        assert alert.severity_id == 4
        assert alert.risk_score == pytest.approx(0.75)
        assert alert.entity_uuid == "u-1"
        assert alert.entity_value == "1.2.3.4"
        assert alert.entity_type == "ip"
        assert alert.contributing_events == (e.event_id,)
        assert alert.mitre_tactics == ("TA0011",)
        assert alert.mitre_techniques == ()
        assert alert.dedup_key == "ioc:ipv4:1.2.3.4:u-1"

    def test_raises_when_event_id_mismatch(self) -> None:
        e = _evt()
        m = _match(str(uuid.uuid4()))
        with pytest.raises(ValueError, match="event_id mismatch"):
            IoCAlertBuilder().build_alert(
                m, e, entity_uuid="u", entity_value="v", entity_type="ip"
            )

    @pytest.mark.parametrize(
        ("confidence", "expected_severity", "expected_risk"),
        [(0, 2, 0.0), (33, 3, 0.33), (67, 4, 0.67), (85, 5, 0.85), (100, 5, 1.0)],
    )
    def test_severity_and_risk_track_confidence(
        self, confidence: int, expected_severity: int, expected_risk: float
    ) -> None:
        e = _evt()
        m = _match(str(e.event_id), confidence=confidence)
        alert = IoCAlertBuilder().build_alert(
            m, e, entity_uuid="u", entity_value="v", entity_type="ip"
        )
        assert alert.severity_id == expected_severity
        assert alert.risk_score == pytest.approx(expected_risk)
