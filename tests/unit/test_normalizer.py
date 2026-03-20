"""Tests for EventNormalizer — RawEvent → SeerflowEvent."""
from __future__ import annotations

import uuid

from seerflow.models.event import SeerflowEvent, SeverityLevel
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
