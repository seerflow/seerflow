"""Unit tests for EventResponse.ioc_matches serialisation (S-069)."""

from __future__ import annotations

import uuid

import pytest

from seerflow.api.schemas import EventResponse
from seerflow.models.event import SeerflowEvent, SeverityLevel


@pytest.mark.unit
def test_event_response_extracts_ioc_matches() -> None:
    e = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1,
        observed_ns=2,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type="syslog",
        message="m",
        attributes={
            "ioc_matches": [
                {
                    "value": "1.2.3.4",
                    "type": "ipv4",
                    "source_feed": "f",
                    "confidence": 80,
                    "kill_chain_phases": ["impact"],
                    "entity_kind": "ip",
                }
            ],
            "other": "ignored",
        },
    )
    resp = EventResponse.from_event(e)
    assert resp.ioc_matches == [
        {
            "value": "1.2.3.4",
            "type": "ipv4",
            "source_feed": "f",
            "confidence": 80,
            "kill_chain_phases": ["impact"],
            "entity_kind": "ip",
        }
    ]


@pytest.mark.unit
def test_event_response_omits_ioc_matches_when_absent() -> None:
    e = SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1,
        observed_ns=2,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type="syslog",
        message="m",
    )
    resp = EventResponse.from_event(e)
    assert resp.ioc_matches is None
