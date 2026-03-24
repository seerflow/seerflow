"""Integration test: 3 receiver sources running simultaneously."""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import grpc
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2
from opentelemetry.proto.resource.v1 import resource_pb2

from seerflow.config import ReceiverConfig, SeerflowConfig
from seerflow.pipeline import build_pipeline


async def test_three_sources_simultaneous() -> None:
    """Start syslog + OTLP gRPC + OTLP HTTP, send one event each, verify all 3 arrive."""
    config = SeerflowConfig(
        receivers=ReceiverConfig(
            syslog_enabled=True,
            syslog_udp_port=0,
            syslog_tcp_port=0,
            syslog_tcp_enabled=False,  # UDP only for simplicity
            otlp_grpc_enabled=True,
            otlp_grpc_port=0,
            otlp_http_enabled=True,
            otlp_http_port=0,
            webhook_enabled=False,
        )
    )
    pipeline = await build_pipeline(config)
    try:
        mgr = pipeline.manager
        # Get actual ports
        syslog_r = mgr._receivers["syslog"]
        grpc_r = mgr._receivers["otlp-grpc"]
        http_r = mgr._receivers["otlp-http"]

        # Send syslog UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(
            b"<134>1 2026-03-24T00:00:00Z host app 1 - - test syslog",
            ("127.0.0.1", syslog_r.udp_port),
        )
        sock.close()

        # Send OTLP gRPC
        channel = grpc.insecure_channel(f"127.0.0.1:{grpc_r.actual_port}")
        stub = logs_service_pb2_grpc.LogsServiceStub(channel)
        record = logs_pb2.LogRecord(body=common_pb2.AnyValue(string_value="grpc test"))
        scope = logs_pb2.ScopeLogs(log_records=[record])
        rl = logs_pb2.ResourceLogs(resource=resource_pb2.Resource(), scope_logs=[scope])
        request = logs_service_pb2.ExportLogsServiceRequest(resource_logs=[rl])
        stub.Export(request)
        channel.close()

        # Send OTLP HTTP
        http_record = logs_pb2.LogRecord(body=common_pb2.AnyValue(string_value="http test"))
        http_scope = logs_pb2.ScopeLogs(log_records=[http_record])
        http_rl = logs_pb2.ResourceLogs(resource=resource_pb2.Resource(), scope_logs=[http_scope])
        http_req = logs_service_pb2.ExportLogsServiceRequest(resource_logs=[http_rl])
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"http://127.0.0.1:{http_r.actual_port}/v1/logs",
                data=http_req.SerializeToString(),
                headers={"Content-Type": "application/x-protobuf"},
            )

        await asyncio.sleep(0.5)  # let events arrive

        # Collect events
        source_types: set[str] = set()
        while mgr.queue_depth > 0:
            event = await mgr.get_event()
            if event:
                source_types.add(event.source_type)

        assert "syslog" in source_types
        assert "otlp_grpc" in source_types
        assert "otlp_http" in source_types
    finally:
        await pipeline.stop()
