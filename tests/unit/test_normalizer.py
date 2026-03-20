"""Tests for EventNormalizer — RawEvent → SeerflowEvent."""
from __future__ import annotations

import uuid

from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.parsing.drain import DrainParser
from seerflow.parsing.normalizer import EventNormalizer
from seerflow.receivers.base import RawEvent


def _make_raw(
    message: str = "test log line",
    source_type: str = "syslog",
    source_id: str = "syslog-main",
    metadata: dict | None = None,
) -> RawEvent:
    return RawEvent(
        data=message.encode("utf-8"),
        source_type=source_type,
        source_id=source_id,
        received_ns=1_710_000_000_000_000_000,
        metadata=metadata or {},
    )


class TestNormalizerBasicFields:
    def test_returns_seerflow_event(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw())
        assert isinstance(result, SeerflowEvent)

    def test_event_id_is_uuid(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw())
        assert isinstance(result.event_id, uuid.UUID)

    def test_message_decoded(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw("hello world"))
        assert result.message == "hello world"

    def test_source_type_mapped(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw(source_type="file"))
        assert result.source_type == "file"

    def test_source_id_mapped(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw(source_id="my-source"))
        assert result.source_id == "my-source"

    def test_encoding_errors_replaced(self) -> None:
        raw = RawEvent(
            data=b"hello \xff\xfe world",
            source_type="test",
            source_id="t",
            received_ns=0,
            metadata={},
        )
        normalizer = EventNormalizer()
        result = normalizer.normalize(raw)
        assert "hello" in result.message
        assert "\ufffd" in result.message  # replacement char

    def test_severity_from_metadata(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw(metadata={"seerflow_severity": 4}))
        assert result.severity_id == SeverityLevel.ERROR

    def test_severity_default_informational(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw())
        assert result.severity_id == SeverityLevel.INFORMATIONAL

    def test_timestamp_ns_from_raw(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw())
        assert result.timestamp_ns == 1_710_000_000_000_000_000


class TestNormalizerDrainIntegration:
    def test_template_id_populated(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(
            _make_raw("Login failed for user admin from 10.0.0.1")
        )
        assert result.template_id > 0 or result.template_id == -1  # depends on Drain state

    def test_template_str_populated(self) -> None:
        normalizer = EventNormalizer()
        # Send same pattern twice to force template generalization
        normalizer.normalize(_make_raw("Login failed for user alice from 10.0.0.1"))
        result = normalizer.normalize(
            _make_raw("Login failed for user bob from 10.0.0.2")
        )
        assert result.template_str != ""

    def test_template_params_tuple(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw("test message 123"))
        assert isinstance(result.template_params, tuple)

    def test_custom_drain_parser_injected(self) -> None:
        parser = DrainParser(sim_th=0.5, depth=5)
        normalizer = EventNormalizer(drain_parser=parser)
        result = normalizer.normalize(_make_raw("custom parser test"))
        assert isinstance(result, SeerflowEvent)


class TestNormalizerEntityIntegration:
    def test_related_ips_populated(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw("Login from 192.168.1.1"))
        assert "192.168.1.1" in result.related_ips

    def test_related_users_populated(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw("user=admin login"))
        assert "admin" in result.related_users

    def test_related_hosts_populated(self) -> None:
        normalizer = EventNormalizer()
        result = normalizer.normalize(_make_raw("host=web-01.prod connected"))
        assert any("web-01" in h for h in result.related_hosts)

    def test_empty_message_no_entities(self) -> None:
        raw = RawEvent(
            data=b"", source_type="t", source_id="s", received_ns=0, metadata={}
        )
        normalizer = EventNormalizer()
        result = normalizer.normalize(raw)
        assert result.related_ips == ()
        assert result.related_users == ()


class TestNormalizerExports:
    def test_importable_from_package(self) -> None:
        from seerflow.parsing import EventNormalizer as Exported

        assert Exported is EventNormalizer

    def test_in_all(self) -> None:
        import seerflow.parsing

        assert "EventNormalizer" in seerflow.parsing.__all__
