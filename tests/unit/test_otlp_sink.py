"""Tests for OTLP alert export sink."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_alert(
    *,
    severity_id: SeverityLevel = SeverityLevel.ERROR,
    rule_name: str = "hst-anomaly",
    alert_type: str = "ml",
    entity_uuid: str = "entity-uuid-001",
    entity_value: str = "10.0.0.1",
    mitre_tactics: tuple[str, ...] = ("TA0001",),
    mitre_techniques: tuple[str, ...] = ("T1078",),
    risk_score: float = 0.85,
    dedup_key: str = "",
    dedup_count: int = 1,
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity_id,
        rule_name=rule_name,
        description=f"Test alert: {rule_name}",
        entity_uuid=entity_uuid,
        entity_value=entity_value,
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=risk_score,
        dedup_key=dedup_key or f"test:{rule_name}",
        dedup_count=dedup_count,
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
    )


# ---------------------------------------------------------------------------
# Severity mapping tests
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    def test_trace_maps_to_1(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.TRACE)
        assert num == 1
        assert text == "TRACE"

    def test_informational_maps_to_9(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.INFORMATIONAL)
        assert num == 9
        assert text == "INFO"

    def test_notice_maps_to_10(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.NOTICE)
        assert num == 10
        assert text == "INFO2"

    def test_warning_maps_to_13(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.WARNING)
        assert num == 13
        assert text == "WARN"

    def test_error_maps_to_17(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.ERROR)
        assert num == 17
        assert text == "ERROR"

    def test_critical_maps_to_21(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.CRITICAL)
        assert num == 21
        assert text == "FATAL"

    def test_fatal_maps_to_24(self) -> None:
        from seerflow.alerting.sinks.otlp import _map_severity

        num, text = _map_severity(SeverityLevel.FATAL)
        assert num == 24
        assert text == "FATAL4"


# ---------------------------------------------------------------------------
# Alert-to-LogRecord conversion tests
# ---------------------------------------------------------------------------


class TestAlertToLogRecord:
    def test_timestamp_copied(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert()
        lr = alert_to_log_record(alert)
        assert lr.time_unix_nano == 1_700_000_000_000_000_000
        assert lr.observed_time_unix_nano == 1_700_000_000_000_000_000

    def test_severity_mapped(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert(severity_id=SeverityLevel.WARNING)
        lr = alert_to_log_record(alert)
        assert lr.severity_number == 13
        assert lr.severity_text == "WARN"

    def test_body_contains_description(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert(rule_name="sigma-brute-force")
        lr = alert_to_log_record(alert)
        assert lr.body.string_value == "Test alert: sigma-brute-force"

    def test_attributes_contain_alert_fields(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert(
            entity_uuid="ent-123",
            entity_value="10.0.0.1",
            risk_score=0.75,
            dedup_key="test:rule1",
            dedup_count=3,
        )
        lr = alert_to_log_record(alert)
        attrs = {a.key: a.value for a in lr.attributes}
        assert attrs["entity.uuid"].string_value == "ent-123"
        assert attrs["entity.value"].string_value == "10.0.0.1"
        assert attrs["entity.type"].string_value == "ip"
        assert attrs["risk.score"].double_value == pytest.approx(0.75)
        assert attrs["dedup.key"].string_value == "test:rule1"
        assert attrs["dedup.count"].int_value == 3

    def test_attributes_contain_mitre_arrays(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert(mitre_tactics=("TA0001", "TA0003"), mitre_techniques=("T1078",))
        lr = alert_to_log_record(alert)
        attrs = {a.key: a.value for a in lr.attributes}
        tactics = [v.string_value for v in attrs["mitre.tactics"].array_value.values]
        assert tactics == ["TA0001", "TA0003"]
        techniques = [v.string_value for v in attrs["mitre.techniques"].array_value.values]
        assert techniques == ["T1078"]

    def test_contributing_events_serialized_as_strings(self) -> None:
        from seerflow.alerting.sinks.otlp import alert_to_log_record

        alert = _make_alert()
        lr = alert_to_log_record(alert)
        attrs = {a.key: a.value for a in lr.attributes}
        events = [v.string_value for v in attrs["contributing.event_ids"].array_value.values]
        assert events == ["12345678-1234-5678-1234-567812345678"]


# ---------------------------------------------------------------------------
# Batch construction tests
# ---------------------------------------------------------------------------


class TestBuildExportRequest:
    def test_single_alert_batch(self) -> None:
        from seerflow.alerting.sinks.otlp import build_export_request

        alerts = [_make_alert()]
        req = build_export_request(alerts)
        assert len(req.resource_logs) == 1
        rl = req.resource_logs[0]
        assert len(rl.scope_logs) == 1
        assert len(rl.scope_logs[0].log_records) == 1

    def test_multiple_alerts_in_single_batch(self) -> None:
        from seerflow.alerting.sinks.otlp import build_export_request

        alerts = [_make_alert(rule_name=f"rule-{i}") for i in range(5)]
        req = build_export_request(alerts)
        assert len(req.resource_logs[0].scope_logs[0].log_records) == 5

    def test_resource_attributes(self) -> None:
        from seerflow.alerting.sinks.otlp import build_export_request

        req = build_export_request([_make_alert()])
        resource = req.resource_logs[0].resource
        attrs = {a.key: a.value.string_value for a in resource.attributes}
        assert attrs["service.name"] == "seerflow"
        assert "service.version" in attrs

    def test_scope_name_and_version(self) -> None:
        from seerflow.alerting.sinks.otlp import build_export_request

        req = build_export_request([_make_alert()])
        scope = req.resource_logs[0].scope_logs[0].scope
        assert scope.name == "seerflow.alerting"
        assert scope.version  # non-empty

    def test_empty_list_raises(self) -> None:
        from seerflow.alerting.sinks.otlp import build_export_request

        with pytest.raises(ValueError, match="empty"):
            build_export_request([])


# ---------------------------------------------------------------------------
# OtlpSink tests
# ---------------------------------------------------------------------------


class TestOtlpSinkEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_adds_to_pending(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", export_interval=5)
        alert = _make_alert()
        sink.enqueue(alert)
        assert len(sink._pending) == 1

    @pytest.mark.asyncio
    async def test_enqueue_drops_when_at_max(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", max_pending=1)
        sink.enqueue(_make_alert())
        sink.enqueue(_make_alert())  # should drop
        assert len(sink._pending) == 1

    @pytest.mark.asyncio
    async def test_enqueue_logs_warning_when_full(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", max_pending=1)
        sink.enqueue(_make_alert())
        with patch("seerflow.alerting.sinks.otlp._log") as mock_log:
            sink.enqueue(_make_alert())
            mock_log.warning.assert_called_once()


class TestOtlpSinkBatching:
    @pytest.mark.asyncio
    async def test_flush_sends_batch(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", export_interval=1)
        sink._send_grpc = AsyncMock()  # type: ignore[assignment]
        for i in range(3):
            sink.enqueue(_make_alert(rule_name=f"rule-{i}"))
        await sink._flush()
        sink._send_grpc.assert_called_once()  # type: ignore[union-attr]
        req = sink._send_grpc.call_args[0][0]  # type: ignore[union-attr]
        assert len(req.resource_logs[0].scope_logs[0].log_records) == 3
        assert len(sink._pending) == 0

    @pytest.mark.asyncio
    async def test_flush_noop_when_empty(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", export_interval=1)
        sink._send_grpc = AsyncMock()  # type: ignore[assignment]
        await sink._flush()
        sink._send_grpc.assert_not_called()  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_flush_uses_http_when_configured(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http", export_interval=1)
        sink._send_http = AsyncMock()  # type: ignore[assignment]
        sink.enqueue(_make_alert())
        await sink._flush()
        sink._send_http.assert_called_once()  # type: ignore[union-attr]


class TestOtlpSinkShutdown:
    @pytest.mark.asyncio
    async def test_stop_flushes_remaining(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", export_interval=60)
        sink._send_grpc = AsyncMock()  # type: ignore[assignment]
        sink.enqueue(_make_alert())
        sink.enqueue(_make_alert())
        await sink.stop()
        # run() should flush and exit
        await asyncio.wait_for(sink.run(), timeout=5.0)
        sink._send_grpc.assert_called_once()  # type: ignore[union-attr]
        req = sink._send_grpc.call_args[0][0]  # type: ignore[union-attr]
        assert len(req.resource_logs[0].scope_logs[0].log_records) == 2
