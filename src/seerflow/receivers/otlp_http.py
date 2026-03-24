"""OTLP HTTP receiver — OpenTelemetry Logs Protocol ingestion over HTTP.

NOT thread-safe for start/stop — designed for single event-loop operation.
The aiohttp handler runs within the same event loop.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import TYPE_CHECKING

import aiohttp.web
from google.protobuf.json_format import Parse, ParseError
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)

_MAX_REQUEST_BYTES = 4 * 1024 * 1024  # 4 MB


class OtlpHttpReceiver:
    """OTLP HTTP receiver for OpenTelemetry log ingestion.

    NOT thread-safe for start/stop — single event-loop only.
    Use ``port=0`` in tests to let the OS assign an ephemeral port.
    Read the actual port via the ``actual_port`` property after ``start()``.
    """

    __slots__ = (
        "_actual_port",
        "_bind_addr",
        "_manager",
        "_port",
        "_runner",
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
        port: int = 4318,
    ) -> None:
        if not bind_addr:
            msg = "bind_addr must be a non-empty string"
            raise ValueError(msg)
        self._manager = manager
        self._source_id = source_id
        self._bind_addr = bind_addr
        self._port = port
        self._runner: aiohttp.web.AppRunner | None = None
        self._actual_port: int = port
        self._started = False
        self._stopped = False

    async def start(self) -> None:
        """Start the HTTP server on the configured address and port."""
        if self._started:
            return
        app = aiohttp.web.Application(client_max_size=_MAX_REQUEST_BYTES)
        app.router.add_post("/v1/logs", self._handle_logs)
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        # Use pre-created socket for reliable ephemeral port discovery
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self._bind_addr, self._port))
            self._actual_port = sock.getsockname()[1]
            site = aiohttp.web.SockSite(runner, sock)
            await site.start()
        except Exception:
            sock.close()
            await runner.cleanup()
            raise
        self._runner = runner
        self._started = True
        _log.info(
            "OTLP HTTP receiver listening on %s:%d",
            self._bind_addr,
            self._actual_port,
        )

    async def stop(self) -> None:
        """Gracefully stop the HTTP server."""
        if self._stopped:
            return
        self._stopped = True
        if self._runner is not None:
            await self._runner.cleanup()
            _log.info("OTLP HTTP receiver stopped")

    def is_healthy(self) -> bool:
        """Return True if the receiver has started and not been stopped."""
        return self._started and not self._stopped

    @property
    def actual_port(self) -> int:
        """Actual bound port (useful when configured with port=0)."""
        return self._actual_port

    async def _handle_logs(
        self,
        request: aiohttp.web.Request,
    ) -> aiohttp.web.Response:
        """Handle POST /v1/logs — accepts protobuf or JSON bodies."""
        content_type = request.content_type
        body = await request.read()
        try:
            if content_type == "application/x-protobuf":
                req = logs_service_pb2.ExportLogsServiceRequest()
                consumed = req.ParseFromString(body)
                if consumed != len(body):
                    return aiohttp.web.Response(
                        status=400, text="Trailing bytes after protobuf message"
                    )
            elif content_type == "application/json":
                req = Parse(body, logs_service_pb2.ExportLogsServiceRequest())
            else:
                return aiohttp.web.Response(status=415, text="Unsupported content type")
        except (ParseError, DecodeError) as exc:
            _log.debug("Malformed request body: %s", exc)
            return aiohttp.web.Response(status=400, text="Malformed request body")
        except Exception:
            _log.exception("Unexpected error parsing OTLP HTTP request")
            return aiohttp.web.Response(status=400, text="Malformed request body")

        for resource_logs in req.resource_logs:
            for scope_logs in resource_logs.scope_logs:
                for log_record in scope_logs.log_records:
                    event = RawEvent(
                        data=log_record.SerializeToString(),
                        source_type="otlp_http",
                        source_id=self._source_id,
                        received_ns=time.time_ns(),
                        metadata={},
                    )
                    if not await self._manager.put_event(event):
                        _log.warning("Queue full, rejecting OTLP HTTP request")
                        return aiohttp.web.Response(status=429, text="Queue full")

        resp_body = logs_service_pb2.ExportLogsServiceResponse().SerializeToString()
        return aiohttp.web.Response(
            status=200,
            body=resp_body,
            content_type="application/x-protobuf",
        )
