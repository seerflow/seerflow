"""Tests for SeerflowEvent msgspec.Struct and SeverityLevel enum."""

from __future__ import annotations

import time
import uuid

import msgspec
import pytest

from seerflow.models.event import SeerflowEvent, SeverityLevel


def _make_event(**overrides: object) -> SeerflowEvent:
    """Helper to create a minimal valid SeerflowEvent."""
    defaults: dict[str, object] = {
        "event_id": uuid.uuid4(),
        "timestamp_ns": time.time_ns(),
        "observed_ns": time.time_ns(),
    }
    defaults.update(overrides)
    return SeerflowEvent(**defaults)  # type: ignore[arg-type]


class TestSeerflowEventCreation:
    def test_create_with_required_fields(self) -> None:
        eid = uuid.uuid4()
        ts = time.time_ns()
        obs = time.time_ns()
        event = SeerflowEvent(event_id=eid, timestamp_ns=ts, observed_ns=obs)

        assert event.event_id == eid
        assert event.timestamp_ns == ts
        assert event.observed_ns == obs
        assert event.severity_id == SeverityLevel.INFORMATIONAL
        assert event.template_id == -1
        assert event.entity_refs == ()
        assert event.risk_score == 0.0

    def test_create_with_all_fields(self) -> None:
        eid = uuid.uuid4()
        event = SeerflowEvent(
            event_id=eid,
            timestamp_ns=1_000_000_000,
            observed_ns=1_000_000_001,
            trace_id="abc123",
            span_id="def456",
            severity_id=SeverityLevel.ERROR,
            otel_severity=17,
            event_kind="alert",
            event_category="network",
            event_type="connection",
            event_outcome="failure",
            event_action="drop",
            category_uid=4,
            class_uid=4001,
            type_uid=400100,
            message="Connection refused",
            body=msgspec.json.encode({"raw": "data"}),
            source_type="syslog",
            source_id="server-01",
            log_source_category="firewall",
            log_source_product="iptables",
            log_source_service="kernel",
            template_id=42,
            template_str="Connection <*> from <*>",
            template_params=("refused", "192.168.1.1"),
            entity_refs=("uuid-1", "uuid-2"),
            related_ips=("192.168.1.1",),
            related_users=("admin",),
            related_hosts=("server-01",),
            mitre_tactics=("TA0001",),
            mitre_techniques=("T1190",),
            risk_score=0.85,
            confidence=0.92,
            anomaly_score=0.78,
            attributes={"custom": "value"},
            tags=("important", "reviewed"),
            raw_event="raw log line here",
            resource_attrs={"host.name": "server-01"},
        )

        assert event.event_id == eid
        assert event.trace_id == "abc123"
        assert event.severity_id == SeverityLevel.ERROR
        assert event.message == "Connection refused"
        assert event.template_id == 42
        assert event.template_params == ("refused", "192.168.1.1")
        assert event.entity_refs == ("uuid-1", "uuid-2")
        assert event.mitre_tactics == ("TA0001",)
        assert event.risk_score == 0.85
        assert event.attributes == {"custom": "value"}
        assert event.tags == ("important", "reviewed")
        assert event.resource_attrs == {"host.name": "server-01"}


class TestSeerflowEventDefaults:
    def test_default_values(self) -> None:
        event = _make_event()

        assert event.trace_id is None
        assert event.span_id is None
        assert event.severity_id == SeverityLevel.INFORMATIONAL
        assert event.otel_severity == 9
        assert event.event_kind == "event"
        assert event.event_category == ""
        assert event.event_type == ""
        assert event.event_outcome == ""
        assert event.event_action == ""
        assert event.category_uid == 0
        assert event.class_uid == 0
        assert event.type_uid == 0
        assert event.message == ""
        assert event.body is None
        assert event.source_type == ""
        assert event.source_id == ""
        assert event.log_source_category == ""
        assert event.log_source_product == ""
        assert event.log_source_service == ""
        assert event.template_id == -1
        assert event.template_str == ""
        assert event.template_params == ()
        assert event.entity_refs == ()
        assert event.related_ips == ()
        assert event.related_users == ()
        assert event.related_hosts == ()
        assert event.mitre_tactics == ()
        assert event.mitre_techniques == ()
        assert event.risk_score == 0.0
        assert event.confidence == 1.0
        assert event.anomaly_score == 0.0
        assert event.attributes == {}
        assert event.tags == ()
        assert event.raw_event == ""
        assert event.resource_attrs == {}

    def test_dict_defaults_are_independent(self) -> None:
        """Verify each instance gets its own dict (not shared mutable default)."""
        e1 = _make_event()
        e2 = _make_event()
        assert e1.attributes is not e2.attributes
        assert e1.resource_attrs is not e2.resource_attrs


class TestSeerflowEventImmutability:
    def test_frozen_rejects_assignment(self) -> None:
        event = _make_event()
        with pytest.raises(AttributeError):
            event.severity_id = SeverityLevel.ERROR  # type: ignore[misc]

    def test_frozen_rejects_new_attribute(self) -> None:
        event = _make_event()
        with pytest.raises(AttributeError):
            event.new_field = "nope"  # type: ignore[attr-defined]

    def test_functional_update_replace(self) -> None:
        event = _make_event(risk_score=0.1)
        updated = msgspec.structs.replace(event, risk_score=0.9)

        assert event.risk_score == 0.1  # original unchanged
        assert updated.risk_score == 0.9
        assert event.event_id == updated.event_id  # other fields preserved
        assert event.timestamp_ns == updated.timestamp_ns


class TestSeerflowEventSerialization:
    def test_msgpack_roundtrip(self) -> None:
        event = _make_event(
            severity_id=SeverityLevel.WARNING,
            message="test message",
            template_id=7,
            entity_refs=("uuid-a", "uuid-b"),
            risk_score=0.5,
            attributes={"key": "val"},
        )
        encoded = msgspec.msgpack.encode(event)
        decoded = msgspec.msgpack.decode(encoded, type=SeerflowEvent)

        assert decoded == event
        assert isinstance(encoded, bytes)

    def test_json_roundtrip(self) -> None:
        event = _make_event(
            severity_id=SeverityLevel.NOTICE,
            message="json test",
            related_ips=("10.0.0.1",),
        )
        encoded = msgspec.json.encode(event)
        decoded = msgspec.json.decode(encoded, type=SeerflowEvent)

        assert decoded == event
        assert isinstance(encoded, bytes)

    def test_json_includes_type_tag(self) -> None:
        event = _make_event()
        raw = msgspec.json.decode(msgspec.json.encode(event))
        assert raw["type"] == "SeerflowEvent"


class TestSeerflowEventValidation:
    def test_decode_missing_required_field_raises(self) -> None:
        """Missing event_id should raise ValidationError on decode."""
        bad_json = b'{"type": "SeerflowEvent", "timestamp_ns": 1, "observed_ns": 2}'
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad_json, type=SeerflowEvent)

    def test_decode_wrong_type_raises(self) -> None:
        """Wrong type for a field should raise ValidationError on decode."""
        bad_json = (
            b'{"type": "SeerflowEvent",'
            b' "event_id": "not-a-uuid",'
            b' "timestamp_ns": 1, "observed_ns": 2}'
        )
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad_json, type=SeerflowEvent)

    def test_decode_invalid_severity_raises(self) -> None:
        """Out-of-range severity_id should raise ValidationError."""
        eid = str(uuid.uuid4())
        bad_json = (
            f'{{"type": "SeerflowEvent",'
            f' "event_id": "{eid}",'
            f' "timestamp_ns": 1, "observed_ns": 2,'
            f' "severity_id": 99}}'
        )
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad_json.encode(), type=SeerflowEvent)


class TestSeverityLevel:
    def test_enum_values(self) -> None:
        assert SeverityLevel.TRACE.value == 0
        assert SeverityLevel.INFORMATIONAL.value == 1
        assert SeverityLevel.NOTICE.value == 2
        assert SeverityLevel.WARNING.value == 3
        assert SeverityLevel.ERROR.value == 4
        assert SeverityLevel.CRITICAL.value == 5
        assert SeverityLevel.FATAL.value == 6

    def test_text_property(self) -> None:
        assert SeverityLevel.TRACE.text == "Trace"
        assert SeverityLevel.INFORMATIONAL.text == "Informational"
        assert SeverityLevel.NOTICE.text == "Notice"
        assert SeverityLevel.WARNING.text == "Warning"
        assert SeverityLevel.ERROR.text == "Error"
        assert SeverityLevel.CRITICAL.text == "Critical"
        assert SeverityLevel.FATAL.text == "Fatal"

    def test_all_levels_covered(self) -> None:
        assert len(SeverityLevel) == 7

    def test_int_compatibility(self) -> None:
        """SeverityLevel values can be used as ints."""
        assert int(SeverityLevel.TRACE) == 0
        assert int(SeverityLevel.FATAL) == 6


class TestSeerflowEventPerformance:
    def test_creation_smoke(self) -> None:
        """Verify 10K creations complete without error."""
        eid = uuid.uuid4()
        ts = time.time_ns()
        obs = ts + 1000
        for _ in range(10_000):
            SeerflowEvent(event_id=eid, timestamp_ns=ts, observed_ns=obs)

    @pytest.mark.slow
    def test_creation_benchmark(self) -> None:
        """Benchmark: 10K creations should complete in <50ms (generous CI budget)."""
        eid = uuid.uuid4()
        ts = time.time_ns()
        obs = ts + 1000

        start = time.perf_counter_ns()
        for _ in range(10_000):
            SeerflowEvent(event_id=eid, timestamp_ns=ts, observed_ns=obs)
        elapsed_ns = time.perf_counter_ns() - start

        elapsed_ms = elapsed_ns / 1_000_000
        avg_us = elapsed_ns / 10_000 / 1_000
        assert elapsed_ms < 50, f"10K creations took {elapsed_ms:.1f}ms (avg {avg_us:.2f}μs/event)"
