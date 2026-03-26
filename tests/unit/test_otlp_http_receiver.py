"""Tests for OtlpHttpReceiver — OTLP HTTP log ingestion."""

from __future__ import annotations

import aiohttp
import pytest
from google.protobuf import json_format
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.resource.v1 import resource_pb2

from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.otlp_http import OtlpHttpReceiver


def _make_export_request(
    num_records: int = 1,
    body_prefix: str = "test log",
) -> logs_service_pb2.ExportLogsServiceRequest:
    """Build an ExportLogsServiceRequest with *num_records* LogRecords."""
    records = [
        logs_pb2.LogRecord(
            time_unix_nano=1_700_000_000_000_000_000 + i,
            observed_time_unix_nano=1_700_000_000_000_000_000 + i,
            severity_number=9,
            severity_text="INFO",
            body=common_pb2.AnyValue(string_value=f"{body_prefix} {i}"),
        )
        for i in range(num_records)
    ]
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


class TestOtlpHttpReceiverProtocol:
    def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        assert isinstance(receiver, Receiver)


class TestOtlpHttpReceiverLifecycle:
    async def test_start_stop_lifecycle(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        assert not receiver.is_healthy()
        await receiver.start()
        assert receiver.is_healthy()
        await receiver.stop()
        assert not receiver.is_healthy()


class TestOtlpHttpReceiverIngest:
    async def test_receive_protobuf(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            request = _make_export_request(num_records=1)
            body = request.SerializeToString()
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=body,
                    headers={"Content-Type": "application/x-protobuf"},
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "otlp_http"
            assert event.source_id == "otlp-http-test"
            assert isinstance(event.data, bytes)
            assert len(event.data) > 0
            assert event.received_ns > 0
        finally:
            await receiver.stop()

    async def test_receive_json(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            request = _make_export_request(num_records=1)
            json_body = json_format.MessageToJson(request)
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=json_body.encode(),
                    headers={"Content-Type": "application/json"},
                )
                assert resp.status == 200
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "otlp_http"
            assert event.source_id == "otlp-http-test"
            assert isinstance(event.data, bytes)
            assert len(event.data) > 0
        finally:
            await receiver.stop()

    async def test_multiple_records(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            request = _make_export_request(num_records=5, body_prefix="multi")
            body = request.SerializeToString()
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=body,
                    headers={"Content-Type": "application/x-protobuf"},
                )
                assert resp.status == 200
            assert mgr.queue_depth == 5
            for _ in range(5):
                event = await mgr.get_event()
                assert event.source_type == "otlp_http"
        finally:
            await receiver.stop()

    async def test_backpressure_429(self) -> None:
        mgr = ReceiverManager(queue_maxsize=1)
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            request = _make_export_request(num_records=3, body_prefix="overflow")
            body = request.SerializeToString()
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=body,
                    headers={"Content-Type": "application/x-protobuf"},
                )
                assert resp.status == 429
        finally:
            await receiver.stop()

    async def test_unsupported_content_type_415(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=b"some text",
                    headers={"Content-Type": "text/plain"},
                )
                assert resp.status == 415
        finally:
            await receiver.stop()

    async def test_malformed_body_400(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=b"\xff\xfe garbage bytes",
                    headers={"Content-Type": "application/x-protobuf"},
                )
                assert resp.status == 400
        finally:
            await receiver.stop()


class TestOtlpHttpReceiverEdgeCases:
    async def test_start_is_idempotent(self) -> None:
        """Second start() call is a no-op (line 71)."""
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        await receiver.start()  # no-op
        assert receiver.is_healthy()
        await receiver.stop()

    async def test_stop_without_start(self) -> None:
        """Stop before start does not crash (line 99)."""
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.stop()
        assert not receiver.is_healthy()

    async def test_stop_is_idempotent(self) -> None:
        """Second stop() call is a no-op."""
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        await receiver.stop()
        await receiver.stop()  # no-op
        assert not receiver.is_healthy()

    async def test_malformed_json_400(self) -> None:
        """Malformed JSON body returns 400 (lines 136-138)."""
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=b"{not valid json at all!!!}",
                    headers={"Content-Type": "application/json"},
                )
                assert resp.status == 400
        finally:
            await receiver.stop()

    async def test_protobuf_trailing_bytes_400(self) -> None:
        """Protobuf with trailing bytes returns 400 (line 126)."""
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            request = _make_export_request(num_records=1)
            body = request.SerializeToString()
            # Append trailing bytes
            body_with_trailing = body + b"\xff\xfe\xfd"
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"http://127.0.0.1:{port}/v1/logs",
                    data=body_with_trailing,
                    headers={"Content-Type": "application/x-protobuf"},
                )
                assert resp.status == 400
        finally:
            await receiver.stop()

    async def test_start_socket_error_propagates(self) -> None:
        """When socket bind fails, exception propagates (lines 84-87)."""
        mgr = ReceiverManager()
        # Start first receiver to occupy a port
        receiver1 = OtlpHttpReceiver(mgr, source_id="r1", port=0)
        await receiver1.start()
        occupied_port = receiver1.actual_port
        try:
            # Try to bind second receiver to same port
            receiver2 = OtlpHttpReceiver(mgr, source_id="r2", port=occupied_port)
            with pytest.raises(OSError):
                await receiver2.start()
        finally:
            await receiver1.stop()


class TestOtlpHttpReceiverConfig:
    async def test_configurable_port(self) -> None:
        mgr = ReceiverManager()
        receiver = OtlpHttpReceiver(mgr, source_id="otlp-http-test", port=0)
        await receiver.start()
        try:
            port = receiver.actual_port
            assert port > 0
            assert port != 4318  # OS-assigned, not default
        finally:
            await receiver.stop()

    def test_empty_bind_addr_rejected(self) -> None:
        mgr = ReceiverManager()
        with pytest.raises(ValueError, match="bind_addr must be a non-empty string"):
            OtlpHttpReceiver(mgr, source_id="test", bind_addr="")


class TestOtlpHttpExports:
    def test_import(self) -> None:
        import seerflow.receivers as mod

        assert hasattr(mod, "OtlpHttpReceiver")

    def test_all(self) -> None:
        import seerflow.receivers as mod

        assert "OtlpHttpReceiver" in mod.__all__
