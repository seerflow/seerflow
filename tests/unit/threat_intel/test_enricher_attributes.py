"""Unit tests for IoCAlertBuilder.enriched_attributes (S-069)."""

from __future__ import annotations

import time
import uuid

import msgspec
import pytest

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.indicator import Indicator
from seerflow.models.ioc_match import IoCMatch
from seerflow.threat_intel.enricher import IOC_MATCHES_MAX_ENTRIES, IoCAlertBuilder


def _evt(*, attrs: dict[str, object] | None = None) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1,
        observed_ns=2,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type="syslog",
        message="m",
        attributes=attrs if attrs is not None else {"foo": "bar"},  # type: ignore[arg-type]
    )


def _ind(*, value: str = "1.2.3.4") -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed="alienvault-otx",
        confidence=75,
        kill_chain_phases=("command-and-control",),
        valid_from_ns=0,
        valid_until_ns=None,
    )


def _match(event_id: str, *, value: str = "1.2.3.4") -> IoCMatch:
    return IoCMatch(
        value=value,
        type="ipv4",
        indicator=_ind(value=value),
        event_id=event_id,
        entity_kind="ip",
        matched_at_ns=time.time_ns(),
    )


@pytest.mark.unit
class TestEnrichedAttributes:
    def test_empty_matches_returns_fresh_copy(self) -> None:
        e = _evt()
        out = IoCAlertBuilder().enriched_attributes(e, [])
        assert out == e.attributes
        assert out is not e.attributes

    def test_single_match_appends_payload(self) -> None:
        e = _evt()
        m = _match(str(e.event_id))
        out = IoCAlertBuilder().enriched_attributes(e, [m])
        assert out["foo"] == "bar"
        assert out["ioc_matches"] == [
            {
                "value": "1.2.3.4",
                "type": "ipv4",
                "source_feed": "alienvault-otx",
                "confidence": 75,
                "kill_chain_phases": ["command-and-control"],
                "entity_kind": "ip",
            }
        ]

    def test_payload_is_json_serialisable(self) -> None:
        e = _evt()
        m = _match(str(e.event_id))
        out = IoCAlertBuilder().enriched_attributes(e, [m])
        msgspec.json.encode(out)  # raises on non-serialisable values

    def test_caps_at_max_entries_and_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        e = _evt()
        eid = str(e.event_id)
        many = [_match(eid, value=f"10.0.0.{i}") for i in range(IOC_MATCHES_MAX_ENTRIES + 5)]
        with caplog.at_level("WARNING", logger="seerflow"):
            out = IoCAlertBuilder().enriched_attributes(e, many)
        assert len(out["ioc_matches"]) == IOC_MATCHES_MAX_ENTRIES
        assert any("ioc_matches truncated" in r.message for r in caplog.records)

    def test_does_not_mutate_input_attributes(self) -> None:
        e = _evt(attrs={"foo": "bar"})
        IoCAlertBuilder().enriched_attributes(e, [_match(str(e.event_id))])
        assert "ioc_matches" not in e.attributes
