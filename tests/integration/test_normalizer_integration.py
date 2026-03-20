"""Integration tests for EventNormalizer — full pipeline with real components."""

from __future__ import annotations

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.entities import EntityExtractor
from seerflow.parsing.normalizer import EventNormalizer
from seerflow.receivers.base import RawEvent


def _raw(msg: str, **meta: int) -> RawEvent:
    return RawEvent(
        data=msg.encode(),
        source_type="syslog",
        source_id="integ",
        received_ns=1_710_000_000_000_000_000,
        metadata=dict(meta),
    )


class TestNormalizerEndToEnd:
    """Full pipeline: bytes → decode → DrainParser → EntityExtractor → SeerflowEvent."""

    def test_full_pipeline_produces_event(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(
            _raw("Login from 192.168.1.1 user=admin on host web-01.prod")
        )
        assert isinstance(result, SeerflowEvent)
        assert "192.168.1.1" in result.related_ips
        assert "admin" in result.related_users
        assert result.source_type == "syslog"

    def test_template_generalizes_across_events(self) -> None:
        normalizer = EventNormalizer()
        normalizer.normalize(_raw("Failed login from 10.0.0.1 user=alice"))
        r2 = normalizer.normalize(_raw("Failed login from 10.0.0.2 user=bob"))
        assert r2.template_id >= 1
        assert "<" in r2.template_str or "*" in r2.template_str  # wildcards

    def test_severity_propagated_from_metadata(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_raw("kernel panic", seerflow_severity=5))
        assert result.severity_id == SeverityLevel.CRITICAL

    def test_injected_components_used(self) -> None:
        parser = DrainParser(sim_th=0.3, depth=3)
        extractor = EntityExtractor(enabled_types=frozenset({"ip"}))
        normalizer = EventNormalizer(drain_parser=parser, entity_extractor=extractor)
        result = normalizer.normalize(_raw("request from 10.0.0.1 user=root"))
        assert "10.0.0.1" in result.related_ips
        assert result.related_users == ()  # user extraction disabled

    def test_encoding_errors_produce_valid_event(self) -> None:
        raw = RawEvent(
            data=b"log \xff\xfe entry",
            source_type="file",
            source_id="test",
            received_ns=0,
            metadata={},
        )
        normalizer = EventNormalizer()
        result = normalizer.normalize(raw)
        assert isinstance(result, SeerflowEvent)
        assert "\ufffd" in result.message
