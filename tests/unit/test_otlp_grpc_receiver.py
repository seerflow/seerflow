"""Tests for OtlpGrpcReceiver — OTLP gRPC log ingestion."""

from __future__ import annotations

import asyncio

import grpc
import pytest
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.resource.v1 import resource_pb2

from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.otlp_grpc import OtlpGrpcReceiver


def _make_export_request(
    num_records: int = 1,
    body_prefix: str = "test log",
) -> logs_service_pb2.ExportLogsServiceRequest:
    """Build an ExportLogsServiceRequest with *num_records* LogRecords."""
    records = []
    for i in range(num_records):
        lr = logs_pb2.LogRecord(
            time_unix_nano=1_700_000_000_000_000_000 + i,
            observed_time_unix_nano=1_700_000_000_000_000_000 + i,
            severity_number=9,  # INFO
            severity_text="INFO",
            body=common_pb2.AnyValue(string_value=f"{body_prefix} {i}"),
        )
        records.append(lr)
    scope_logs = logs_pb2.ScopeLogs(log_records=records)
    resource_logs = logs_pb2.ResourceLogs(
        resource=resource_pb2.Resource(
            attributes=[
                common_pb2.KeyValue(
                    key="service.name",
                    value=common_pb2.AnyValue(string_value="test-service"),
                ),
            ],
        ),
        scope_logs=[scope_logs],
    )
    return logs_service_pb2.ExportLogsServiceRequest(resource_logs=[resource_logs])


class TestOtlpGrpcReceiverProtocol:
    def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        assert isinstance(receiver, Receiver)


class TestOtlpGrpcReceiverLifecycle:
    async def test_start_stop_lifecycle(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        assert receiver.is_healthy()
        await receiver.stop()
        assert not receiver.is_healthy()

    async def test_start_is_idempotent(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        await receiver.start()  # second call should be a no-op
        assert receiver.is_healthy()
        await receiver.stop()

    async def test_stop_is_idempotent(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        await receiver.stop()
        await receiver.stop()  # second call should be a no-op
        assert not receiver.is_healthy()


class TestOtlpGrpcReceiverIngest:
    async def test_receive_single_log_record(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = logs_service_pb2_grpc.LogsServiceStub(channel)
            request = _make_export_request(num_records=1)
            stub.Export(request)
            channel.close()

            await asyncio.sleep(0.1)
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "otlp_grpc"
            assert event.source_id == "otlp-test"
            assert isinstance(event.data, bytes)
            assert len(event.data) > 0
            assert event.received_ns > 0
        finally:
            await receiver.stop()

    async def test_receive_multiple_records(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = logs_service_pb2_grpc.LogsServiceStub(channel)
            request = _make_export_request(num_records=5, body_prefix="multi")
            stub.Export(request)
            channel.close()

            await asyncio.sleep(0.1)
            assert mgr.queue_depth == 5
            for _ in range(5):
                event = await mgr.get_event()
                assert event.source_type == "otlp_grpc"
        finally:
            await receiver.stop()

    async def test_backpressure_resource_exhausted(self) -> None:
        mgr = ReceiverManager(queue_maxsize=2)
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = logs_service_pb2_grpc.LogsServiceStub(channel)

            request = _make_export_request(num_records=5, body_prefix="overflow")
            with pytest.raises(grpc.RpcError) as exc_info:
                stub.Export(request)
            assert exc_info.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED

            channel.close()
        finally:
            await receiver.stop()

    async def test_empty_request(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = logs_service_pb2_grpc.LogsServiceStub(channel)
            request = logs_service_pb2.ExportLogsServiceRequest()
            response = stub.Export(request)
            channel.close()

            assert response is not None
            assert mgr.queue_depth == 0
        finally:
            await receiver.stop()


class TestOtlpGrpcReceiverEdgeCases:
    async def test_bind_failure_raises_os_error(self) -> None:
        """When gRPC server fails to bind, OSError is raised (lines 114-115)."""
        from unittest.mock import MagicMock, patch

        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="test", port=0)

        # Mock grpc.server to return a server that reports bind failure (port=0)
        mock_server = MagicMock()
        mock_server.add_insecure_port.return_value = 0  # 0 means bind failed
        with (
            patch("seerflow.receivers.otlp_grpc.grpc.server", return_value=mock_server),
            pytest.raises(OSError, match="failed to bind"),
        ):
            await receiver.start()

    async def test_server_start_exception_stops_server(self) -> None:
        """When server.start() fails, server.stop(0) is called (lines 118-120)."""
        from unittest.mock import MagicMock, patch

        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="test", port=0)

        mock_server = MagicMock()
        mock_server.add_insecure_port.return_value = 50051  # bind succeeds
        mock_server.start.side_effect = RuntimeError("start failed")
        with (
            patch("seerflow.receivers.otlp_grpc.grpc.server", return_value=mock_server),
            pytest.raises(RuntimeError, match="start failed"),
        ):
            await receiver.start()
        mock_server.stop.assert_called_once_with(0)


class TestOtlpGrpcReceiverConfig:
    async def test_configurable_port(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpGrpcReceiver(mgr, source_id="otlp-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            assert port > 0
            assert port != 4317  # OS-assigned, not default

            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = logs_service_pb2_grpc.LogsServiceStub(channel)
            request = _make_export_request(num_records=1)
            stub.Export(request)
            channel.close()

            await asyncio.sleep(0.1)
            assert mgr.queue_depth == 1
        finally:
            await receiver.stop()

    def test_empty_bind_addr_rejected(self) -> None:
        mgr = ReceiverManager()
        with pytest.raises(ValueError, match="bind_addr must be a non-empty string"):
            OtlpGrpcReceiver(mgr, source_id="test", bind_addr="")


class TestOtlpGrpcExports:
    def test_import(self) -> None:
        import seerflow.receivers as mod

        assert hasattr(mod, "OtlpGrpcReceiver")

    def test_all(self) -> None:
        import seerflow.receivers as mod

        assert "OtlpGrpcReceiver" in mod.__all__
