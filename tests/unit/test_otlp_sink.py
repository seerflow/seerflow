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
        assert sink._pending.qsize() == 1

    @pytest.mark.asyncio
    async def test_enqueue_drops_when_at_max(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc", max_pending=1)
        sink.enqueue(_make_alert())
        sink.enqueue(_make_alert())  # should drop
        assert sink._pending.qsize() == 1

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
        assert sink._pending.empty()

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


class TestOtlpSinkGrpcRetry:
    @pytest.mark.asyncio
    async def test_grpc_retry_on_rpc_error(self) -> None:
        import grpc

        from seerflow.alerting.sinks.otlp import OtlpSink

        call_count = 0

        async def fake_export(request: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                error = grpc.aio.AioRpcError(
                    code=grpc.StatusCode.UNAVAILABLE,
                    initial_metadata=grpc.aio.Metadata(),
                    trailing_metadata=grpc.aio.Metadata(),
                    details="connection refused",
                    debug_error_string=None,
                )
                raise error

        mock_channel = MagicMock()
        mock_stub = MagicMock()
        mock_stub.Export = fake_export
        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        sink._grpc_channel = mock_channel

        with (
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
            patch("seerflow.alerting.sinks.otlp.asyncio") as mock_asyncio,
        ):
            mock_asyncio.sleep = AsyncMock()
            sink.enqueue(_make_alert())
            await sink._flush()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_grpc_exhausts_retries_logs_error(self) -> None:
        import grpc

        from seerflow.alerting.sinks.otlp import OtlpSink

        async def always_fail(request: object) -> None:
            error = grpc.aio.AioRpcError(
                code=grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
                details="connection refused",
                debug_error_string=None,
            )
            raise error

        mock_channel = MagicMock()
        mock_stub = MagicMock()
        mock_stub.Export = always_fail
        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        sink._grpc_channel = mock_channel

        with (
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
            patch("seerflow.alerting.sinks.otlp.asyncio") as mock_asyncio,
            patch("seerflow.alerting.sinks.otlp._log") as mock_log,
        ):
            mock_asyncio.sleep = AsyncMock()
            sink.enqueue(_make_alert())
            await sink._flush()
            mock_log.error.assert_called_once()


class TestOtlpSinkHttpTransport:
    @pytest.mark.asyncio
    async def test_http_posts_protobuf_with_correct_headers(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_mock = MagicMock(status=200)
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session
        sink.enqueue(_make_alert())
        await sink._flush()

        session.post.assert_called_once()
        call_kwargs = session.post.call_args[1]
        assert call_kwargs["headers"]["Content-Type"] == "application/x-protobuf"
        assert isinstance(call_kwargs["data"], bytes)

    @pytest.mark.asyncio
    async def test_http_appends_v1_logs_to_endpoint(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_mock = MagicMock(status=200)
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session
        sink.enqueue(_make_alert())
        await sink._flush()

        url = session.post.call_args[0][0]
        assert url == "http://localhost:4318/v1/logs"

    @pytest.mark.asyncio
    async def test_http_no_retry_on_4xx(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_mock = MagicMock(status=400)
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session
        sink.enqueue(_make_alert())
        await sink._flush()

        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_http_retry_on_5xx(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_fail = MagicMock(status=500)
        resp_ok = MagicMock(status=200)
        cm_fail = AsyncMock()
        cm_fail.__aenter__ = AsyncMock(return_value=resp_fail)
        cm_fail.__aexit__ = AsyncMock(return_value=False)
        cm_ok = AsyncMock()
        cm_ok.__aenter__ = AsyncMock(return_value=resp_ok)
        cm_ok.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(side_effect=[cm_fail, cm_ok])

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session

        with patch("seerflow.alerting.sinks.otlp.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            sink.enqueue(_make_alert())
            await sink._flush()

        assert session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_http_uses_allow_redirects_false(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_mock = MagicMock(status=200)
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session
        sink.enqueue(_make_alert())
        await sink._flush()

        call_kwargs = session.post.call_args[1]
        assert call_kwargs.get("allow_redirects") is False


class TestNormalizeGrpcEndpoint:
    def test_strips_http(self) -> None:
        from seerflow.alerting.sinks.otlp import _normalize_grpc_endpoint

        assert _normalize_grpc_endpoint("http://localhost:4317") == "localhost:4317"

    def test_strips_https(self) -> None:
        from seerflow.alerting.sinks.otlp import _normalize_grpc_endpoint

        assert (
            _normalize_grpc_endpoint("https://collector.example.com:4317")
            == "collector.example.com:4317"
        )

    def test_no_scheme_unchanged(self) -> None:
        from seerflow.alerting.sinks.otlp import _normalize_grpc_endpoint

        assert _normalize_grpc_endpoint("localhost:4317") == "localhost:4317"


class TestMaskedUrl:
    def test_http_url_masked(self) -> None:
        from seerflow.alerting.sinks.otlp import masked_url

        assert (
            masked_url("http://collector.example.com:4318") == "http://collector.example.com/***"
        )

    def test_https_url_masked(self) -> None:
        from seerflow.alerting.sinks.otlp import masked_url

        assert masked_url("https://otel.internal:4318/v1/logs") == "https://otel.internal/***"

    def test_bare_host_port_masked(self) -> None:
        from seerflow.alerting.sinks.otlp import masked_url

        assert masked_url("localhost:4317") == "grpc://localhost/***"

    def test_bare_hostname_masked(self) -> None:
        from seerflow.alerting.sinks.otlp import masked_url

        assert masked_url("collector.example.com:4317") == "grpc://collector.example.com/***"

    def test_empty_string(self) -> None:
        from seerflow.alerting.sinks.otlp import masked_url

        assert masked_url("") == "<invalid-url>"


class TestGetVersion:
    def test_returns_dev_when_package_not_found(self) -> None:
        import importlib.metadata

        from seerflow.alerting.sinks.otlp import _get_version

        with patch.object(
            importlib.metadata,
            "version",
            side_effect=importlib.metadata.PackageNotFoundError("seerflow"),
        ):
            assert _get_version() == "dev"


class TestOtlpSinkClose:
    @pytest.mark.asyncio
    async def test_close_grpc_channel_when_open(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        mock_channel = AsyncMock()
        sink._grpc_channel = mock_channel
        await sink.close()
        mock_channel.close.assert_awaited_once()
        assert sink._grpc_channel is None

    @pytest.mark.asyncio
    async def test_close_http_session_when_open(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        mock_session = AsyncMock()
        sink._http_session = mock_session
        await sink.close()
        mock_session.close.assert_awaited_once()
        assert sink._http_session is None


class TestOtlpSinkGrpcChannelCreation:
    @pytest.mark.asyncio
    async def test_grpc_creates_channel_when_none(self) -> None:
        import grpc.aio

        from seerflow.alerting.sinks.otlp import OtlpSink

        mock_stub = MagicMock()
        mock_stub.Export = AsyncMock()
        mock_channel = MagicMock()

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        assert sink._grpc_channel is None

        with (
            patch.object(grpc.aio, "insecure_channel", return_value=mock_channel),
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
        ):
            sink.enqueue(_make_alert())
            await sink._flush()

        assert sink._grpc_channel is mock_channel
        mock_stub.Export.assert_awaited_once()


class TestOtlpSinkGrpcGenericException:
    @pytest.mark.asyncio
    async def test_grpc_generic_exception_propagates_to_flush(self) -> None:
        """Non-RpcError exceptions in _send_grpc propagate to _flush's try/except."""
        from seerflow.alerting.sinks.otlp import OtlpSink

        async def always_fail(request: object) -> None:
            raise ConnectionError("network blip")

        mock_channel = MagicMock()
        mock_stub = MagicMock()
        mock_stub.Export = always_fail
        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        sink._grpc_channel = mock_channel

        with (
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
            patch("seerflow.alerting.sinks.otlp._log") as mock_log,
        ):
            sink.enqueue(_make_alert())
            await sink._flush()
            mock_log.exception.assert_called_once()


class TestOtlpSinkConcurrentEnqueue:
    @pytest.mark.asyncio
    async def test_high_volume_sync_enqueue(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", max_pending=2000)
        for _ in range(1000):
            sink.enqueue(_make_alert())
        assert sink._pending.qsize() == 1000

    @pytest.mark.asyncio
    async def test_queue_full_drops_and_warns(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", max_pending=1)
        sink.enqueue(_make_alert())
        with patch("seerflow.alerting.sinks.otlp._log") as mock_log:
            sink.enqueue(_make_alert())
            mock_log.warning.assert_called_once()
        assert sink._pending.qsize() == 1

    @pytest.mark.asyncio
    async def test_threadsafe_enqueue_via_call_soon_threadsafe(self) -> None:
        import threading

        from seerflow.alerting.sinks.otlp import OtlpSink

        loop = asyncio.get_running_loop()
        sink = OtlpSink(endpoint="host:4317", protocol="grpc", max_pending=500)

        done = threading.Event()

        def worker() -> None:
            for _ in range(100):
                loop.call_soon_threadsafe(sink.enqueue, _make_alert())
            done.set()

        t = threading.Thread(target=worker)
        t.start()
        await asyncio.to_thread(done.wait)
        for _ in range(5):
            await asyncio.sleep(0)
        t.join(timeout=2.0)
        assert sink._pending.qsize() == 100

    @pytest.mark.asyncio
    async def test_flush_drains_queue(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc")
        sink._send_grpc = AsyncMock()  # type: ignore[method-assign]
        for i in range(3):
            sink.enqueue(_make_alert(rule_name=f"rule-{i}"))
        await sink._flush()
        assert sink._pending.empty()
        sink._send_grpc.assert_called_once()  # type: ignore[attr-defined]
        req = sink._send_grpc.call_args[0][0]  # type: ignore[attr-defined]
        assert len(req.resource_logs[0].scope_logs[0].log_records) == 3


class TestOtlpSinkFastShutdown:
    @pytest.mark.asyncio
    async def test_stop_exits_within_one_second_even_with_long_interval(self) -> None:
        import time

        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", export_interval=60)
        sink._send_grpc = AsyncMock()  # type: ignore[method-assign]

        run_task = asyncio.create_task(sink.run())
        await asyncio.sleep(0.05)

        start = time.monotonic()
        await sink.stop()
        await asyncio.wait_for(run_task, timeout=2.0)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"stop() took {elapsed:.3f}s; should be < 1s"

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", export_interval=60)
        sink._send_grpc = AsyncMock()  # type: ignore[method-assign]

        await sink.stop()
        await sink.stop()
        assert sink._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_final_flush_runs_even_if_stop_set_before_run(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", export_interval=60)
        sink._send_grpc = AsyncMock()  # type: ignore[method-assign]
        sink.enqueue(_make_alert())

        await sink.stop()
        await asyncio.wait_for(sink.run(), timeout=2.0)

        sink._send_grpc.assert_called_once()  # type: ignore[attr-defined]


class TestOtlpSinkGrpcTls:
    @pytest.mark.asyncio
    async def test_grpc_uses_secure_channel_when_tls_true(self) -> None:
        import grpc as _grpc
        import grpc.aio

        from seerflow.alerting.sinks.otlp import OtlpSink

        mock_stub = MagicMock()
        mock_stub.Export = AsyncMock()
        mock_channel = MagicMock()

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", tls=True)

        with (
            patch.object(grpc.aio, "secure_channel", return_value=mock_channel) as secure,
            patch.object(grpc.aio, "insecure_channel") as insecure,
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
        ):
            sink.enqueue(_make_alert())
            await sink._flush()

        secure.assert_called_once()
        insecure.assert_not_called()
        args, _kwargs = secure.call_args
        assert args[0] == "host:4317"
        assert isinstance(args[1], _grpc.ChannelCredentials)

    @pytest.mark.asyncio
    async def test_grpc_uses_insecure_channel_when_tls_false(self) -> None:
        import grpc.aio

        from seerflow.alerting.sinks.otlp import OtlpSink

        mock_stub = MagicMock()
        mock_stub.Export = AsyncMock()
        mock_channel = MagicMock()

        sink = OtlpSink(endpoint="host:4317", protocol="grpc", tls=False)

        with (
            patch.object(grpc.aio, "secure_channel") as secure,
            patch.object(grpc.aio, "insecure_channel", return_value=mock_channel) as insecure,
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
        ):
            sink.enqueue(_make_alert())
            await sink._flush()

        insecure.assert_called_once_with("host:4317")
        secure.assert_not_called()

    @pytest.mark.asyncio
    async def test_grpc_auto_tls_from_https_scheme(self) -> None:
        import grpc.aio

        from seerflow.alerting.sinks.otlp import OtlpSink

        mock_stub = MagicMock()
        mock_stub.Export = AsyncMock()
        mock_channel = MagicMock()

        sink = OtlpSink(endpoint="https://collector.example.com:4317", protocol="grpc")

        with (
            patch.object(grpc.aio, "secure_channel", return_value=mock_channel) as secure,
            patch("seerflow.alerting.sinks.otlp.LogsServiceStub", return_value=mock_stub),
        ):
            sink.enqueue(_make_alert())
            await sink._flush()

        secure.assert_called_once()
        target = secure.call_args[0][0]
        assert target == "collector.example.com:4317"


class TestResolveTls:
    def test_explicit_true_wins(self) -> None:
        from seerflow.alerting.sinks.otlp import _resolve_tls

        assert _resolve_tls("http://host:4317", tls=True) is True

    def test_explicit_false_wins(self) -> None:
        from seerflow.alerting.sinks.otlp import _resolve_tls

        assert _resolve_tls("https://host:4317", tls=False) is False

    def test_none_with_https_scheme_enables_tls(self) -> None:
        from seerflow.alerting.sinks.otlp import _resolve_tls

        assert _resolve_tls("https://host:4317", tls=None) is True

    def test_none_with_http_scheme_disables_tls(self) -> None:
        from seerflow.alerting.sinks.otlp import _resolve_tls

        assert _resolve_tls("http://host:4317", tls=None) is False

    def test_none_with_bare_host_port_disables_tls(self) -> None:
        from seerflow.alerting.sinks.otlp import _resolve_tls

        assert _resolve_tls("host:4317", tls=None) is False


class TestOtlpSinkTlsInit:
    def test_init_accepts_tls_kwarg(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(
            endpoint="https://host:4317", protocol="grpc", tls=True,
        )
        assert sink._use_tls is True

    def test_init_auto_detects_tls_from_https_scheme(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="https://host:4317", protocol="grpc")
        assert sink._use_tls is True

    def test_init_defaults_plaintext_for_bare_endpoint(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        sink = OtlpSink(endpoint="host:4317", protocol="grpc")
        assert sink._use_tls is False

    def test_init_warns_on_https_with_tls_false(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from seerflow.alerting.sinks.otlp import OtlpSink

        with caplog.at_level(logging.WARNING, logger="seerflow"):
            OtlpSink(endpoint="https://host:4317", protocol="grpc", tls=False)
        messages = [rec.message for rec in caplog.records]
        assert any(
            "mismatch" in m.lower() or "otlp_tls=false" in m.lower() for m in messages
        )
        assert not any("https://host:4317" in m for m in messages)


class TestOtlpSinkHttpExhaustsRetries:
    @pytest.mark.asyncio
    async def test_http_logs_error_after_all_retries_exhausted(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        resp_mock = MagicMock(status=500)
        resp_cm = AsyncMock()
        resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
        resp_cm.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post = MagicMock(return_value=resp_cm)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session

        with (
            patch("seerflow.alerting.sinks.otlp.asyncio") as mock_asyncio,
            patch("seerflow.alerting.sinks.otlp._log") as mock_log,
        ):
            mock_asyncio.sleep = AsyncMock()
            sink.enqueue(_make_alert())
            await sink._flush()

        mock_log.error.assert_called_once()
        assert session.post.call_count == 3

    @pytest.mark.asyncio
    async def test_http_generic_exception_triggers_retry(self) -> None:
        from seerflow.alerting.sinks.otlp import OtlpSink

        call_count = 0

        def flaky_post(*_args: object, **_kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("network blip")
            resp_mock = MagicMock(status=200)
            resp_cm = AsyncMock()
            resp_cm.__aenter__ = AsyncMock(return_value=resp_mock)
            resp_cm.__aexit__ = AsyncMock(return_value=False)
            return resp_cm

        session = MagicMock()
        session.post = MagicMock(side_effect=flaky_post)

        sink = OtlpSink(endpoint="http://localhost:4318", protocol="http")
        sink._http_session = session

        with patch("seerflow.alerting.sinks.otlp.asyncio") as mock_asyncio:
            mock_asyncio.sleep = AsyncMock()
            sink.enqueue(_make_alert())
            await sink._flush()

        assert call_count == 2
