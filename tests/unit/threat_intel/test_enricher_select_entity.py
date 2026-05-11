"""Unit tests for IoCAlertBuilder.select_entity_uuid (S-069)."""

from __future__ import annotations

import time
import uuid

import pytest

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.indicator import Indicator
from seerflow.models.ioc_match import IoCMatch
from seerflow.threat_intel.enricher import IoCAlertBuilder


def _evt(**kwargs: object) -> SeerflowEvent:
    base = dict(
        event_id=uuid.uuid4(),
        timestamp_ns=1,
        observed_ns=2,
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type="syslog",
        message="m",
        related_ips=(),
        related_domains=(),
        related_hashes=(),
        attributes={},
    )
    base.update(kwargs)
    return SeerflowEvent(**base)  # type: ignore[arg-type]


def _match(event_id: str, *, value: str, ind_type: str, kind: str) -> IoCMatch:
    return IoCMatch(
        value=value,
        type=ind_type,  # type: ignore[arg-type]
        indicator=Indicator(
            value=value,
            type=ind_type,  # type: ignore[arg-type]
            source_feed="f",
            confidence=50,
            kill_chain_phases=(),
            valid_from_ns=0,
            valid_until_ns=None,
        ),
        event_id=event_id,
        entity_kind=kind,  # type: ignore[arg-type]
        matched_at_ns=time.time_ns(),
    )


@pytest.mark.unit
class TestSelectEntityUuid:
    def test_ipv4_match_resolves_to_positional_uuid(self) -> None:
        e = _evt(related_ips=("10.0.0.1", "1.2.3.4"), entity_refs=("u-a", "u-b"))
        m = _match(str(e.event_id), value="1.2.3.4", ind_type="ipv4", kind="ip")
        typed = [("ip", "u-a"), ("ip", "u-b")]
        uid, val, etype = IoCAlertBuilder().select_entity_uuid(e, m, e.entity_refs, typed)
        assert (uid, val, etype) == ("u-b", "1.2.3.4", "ip")

    def test_domain_match_resolves(self) -> None:
        e = _evt(
            related_domains=("evil.example",),
            entity_refs=("u-d",),
        )
        m = _match(str(e.event_id), value="evil.example", ind_type="domain", kind="domain")
        typed = [("domain", "u-d")]
        uid, val, etype = IoCAlertBuilder().select_entity_uuid(e, m, e.entity_refs, typed)
        assert (uid, val, etype) == ("u-d", "evil.example", "domain")

    def test_url_match_with_no_url_entity_falls_back_to_empty(self) -> None:
        e = _evt(entity_refs=("u-only-ip",), attributes={"url": "http://evil/"})
        m = _match(str(e.event_id), value="http://evil/", ind_type="url", kind="url")
        uid, val, _etype = IoCAlertBuilder().select_entity_uuid(
            e, m, e.entity_refs, [("ip", "u-only-ip")]
        )
        assert uid == ""
        assert val == "http://evil/"

    def test_hash_match_falls_back_to_empty_when_no_file_entity(self) -> None:
        e = _evt(entity_refs=())
        m = _match(str(e.event_id), value="abcd", ind_type="sha256", kind="hash")
        uid, val, _etype = IoCAlertBuilder().select_entity_uuid(e, m, (), [])
        assert uid == ""
        assert val == "abcd"

    def test_ip_value_not_in_related_ips_returns_empty(self) -> None:
        # match.value is not present in event.related_ips → ValueError path.
        e = _evt(related_ips=("10.0.0.1",), entity_refs=("u-a",))
        m = _match(str(e.event_id), value="9.9.9.9", ind_type="ipv4", kind="ip")
        uid, val, etype = IoCAlertBuilder().select_entity_uuid(
            e, m, e.entity_refs, [("ip", "u-a")]
        )
        assert (uid, val, etype) == ("", "9.9.9.9", "ip")

    def test_ip_value_present_but_no_matching_typed_entry(self) -> None:
        # match.value IS in related_ips, but typed_for_edges has no "ip" entry
        # at the matching positional index → final empty-return fallthrough.
        e = _evt(related_ips=("1.2.3.4",), entity_refs=("u-a",))
        m = _match(str(e.event_id), value="1.2.3.4", ind_type="ipv4", kind="ip")
        # All typed entries are non-ip → loop completes without returning.
        uid, val, etype = IoCAlertBuilder().select_entity_uuid(
            e, m, e.entity_refs, [("domain", "u-a")]
        )
        assert (uid, val, etype) == ("", "1.2.3.4", "ip")
