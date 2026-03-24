"""OTLP gRPC receiver — OpenTelemetry Logs Protocol ingestion."""

from __future__ import annotations

import logging
import time
from concurrent import futures
from typing import TYPE_CHECKING

import grpc
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)

_GRPC_THREAD_POOL_SIZE = 4
_GRACEFUL_SHUTDOWN_SECONDS = 5


class _LogsServicer(logs_service_pb2_grpc.LogsServiceServicer):
    """gRPC servicer that converts OTLP LogRecords into RawEvents.

    Runs inside the gRPC thread pool — uses ``manager.put_event_sync()``
    instead of the async ``put_event()``.
    """

    __slots__ = ("_manager", "_source_id")

    def __init__(self, manager: ReceiverManager, source_id: str) -> None:
        self._manager = manager
        self._source_id = source_id

    def Export(  # noqa: N802  — gRPC generated method name
        self,
        request: logs_service_pb2.ExportLogsServiceRequest,
        context: grpc.ServicerContext,
    ) -> logs_service_pb2.ExportLogsServiceResponse:
        """Handle an ExportLogsServiceRequest by enqueuing each LogRecord."""
        for resource_logs in request.resource_logs:
            for scope_logs in resource_logs.scope_logs:
                for log_record in scope_logs.log_records:
                    event = RawEvent(
                        data=log_record.SerializeToString(),
                        source_type="otlp_grpc",
                        source_id=self._source_id,
                        received_ns=time.time_ns(),
                        metadata={},
                    )
                    if not self._manager.put_event_sync(event):
                        _log.warning("Queue full, rejecting OTLP request")
                        context.set_code(grpc.StatusCode.RESOURCE_EXHAUSTED)
                        context.set_details("Event queue is full")
                        return logs_service_pb2.ExportLogsServiceResponse()
        return logs_service_pb2.ExportLogsServiceResponse()


class OtlpGrpcReceiver:
    """OTLP gRPC receiver for OpenTelemetry log ingestion.

    Use ``port=0`` in tests to let the OS assign an ephemeral port.
    Read the actual port via the ``actual_port`` property after ``start()``.
    """

    __slots__ = (
        "_actual_port",
        "_bind_addr",
        "_manager",
        "_port",
        "_server",
        "_source_id",
        "_started",
        "_stopped",
    )

    def __init__(
        self,
        manager: ReceiverManager,
        *,
        source_id: str,
        bind_addr: str = "0.0.0.0",  # noqa: S104  # nosec B104 — receiver must listen on all interfaces
        port: int = 4317,
    ) -> None:
        if not bind_addr:
            msg = "bind_addr must be a non-empty string"
            raise ValueError(msg)
        self._manager = manager
        self._source_id = source_id
        self._bind_addr = bind_addr
        self._port = port
        self._server: grpc.Server | None = None
        self._actual_port: int = port
        self._started = False
        self._stopped = False

    async def start(self) -> None:
        """Start the gRPC server on the configured address and port."""
        if self._started:
            return
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=_GRPC_THREAD_POOL_SIZE))
        servicer = _LogsServicer(self._manager, self._source_id)
        logs_service_pb2_grpc.add_LogsServiceServicer_to_server(servicer, server)  # type: ignore[no-untyped-call]
        self._actual_port = server.add_insecure_port(f"{self._bind_addr}:{self._port}")
        server.start()
        self._server = server
        self._started = True
        _log.info("OTLP gRPC receiver listening on %s:%d", self._bind_addr, self._actual_port)

    async def stop(self) -> None:
        """Gracefully stop the gRPC server."""
        if self._stopped:
            return
        self._stopped = True
        if self._server is not None:
            self._server.stop(grace=_GRACEFUL_SHUTDOWN_SECONDS)
            _log.info("OTLP gRPC receiver stopped")

    def is_healthy(self) -> bool:
        """Return True if the receiver has started and not been stopped."""
        return self._started and not self._stopped

    @property
    def actual_port(self) -> int:
        """Actual bound port (useful when configured with port=0)."""
        return self._actual_port
