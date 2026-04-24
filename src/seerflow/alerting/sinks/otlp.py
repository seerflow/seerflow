"""OTLP alert export sink — batch gRPC + HTTP transport."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import logging
from asyncio import QueueEmpty, QueueFull
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import aiohttp
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.logs.v1.logs_service_pb2_grpc import (
    LogsServiceStub,
)
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    InstrumentationScope,
    KeyValue,
)
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord, ResourceLogs, ScopeLogs
from opentelemetry.proto.resource.v1.resource_pb2 import Resource

if TYPE_CHECKING:
    import grpc.aio

    from seerflow.models.alert import Alert
    from seerflow.models.event import SeverityLevel

_log = logging.getLogger("seerflow")

# ---------------------------------------------------------------------------
# Severity mapping: Seerflow SeverityLevel (0-6) → OTel SeverityNumber + text
# ---------------------------------------------------------------------------

_SEVERITY_MAP: dict[int, tuple[int, str]] = {
    0: (1, "TRACE"),  # TRACE
    1: (9, "INFO"),  # INFORMATIONAL
    2: (10, "INFO2"),  # NOTICE
    3: (13, "WARN"),  # WARNING
    4: (17, "ERROR"),  # ERROR
    5: (21, "FATAL"),  # CRITICAL
    6: (24, "FATAL4"),  # FATAL
}


def _map_severity(severity_id: SeverityLevel) -> tuple[int, str]:
    """Map Seerflow SeverityLevel to (OTel SeverityNumber, OTel SeverityText)."""
    return _SEVERITY_MAP.get(int(severity_id), (9, "INFO"))


# ---------------------------------------------------------------------------
# Protobuf helpers
# ---------------------------------------------------------------------------


def _str_kv(key: str, value: str) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(string_value=value))


def _double_kv(key: str, value: float) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(double_value=value))


def _int_kv(key: str, value: int) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(int_value=value))


def _str_array_kv(key: str, values: tuple[str, ...]) -> KeyValue:
    return KeyValue(
        key=key,
        value=AnyValue(
            array_value=ArrayValue(
                values=[AnyValue(string_value=v) for v in values],
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Alert → OTel LogRecord conversion
# ---------------------------------------------------------------------------


def alert_to_log_record(alert: Alert) -> LogRecord:
    """Convert a Seerflow Alert to an OTel LogRecord protobuf."""
    severity_number, severity_text = _map_severity(alert.severity_id)
    return LogRecord(
        time_unix_nano=alert.timestamp_ns,
        observed_time_unix_nano=alert.timestamp_ns,
        severity_number=severity_number,  # type: ignore[arg-type]
        severity_text=severity_text,
        body=AnyValue(string_value=alert.description),
        attributes=[
            _str_kv("alert.id", alert.alert_id),
            _str_kv("alert.type", alert.alert_type),
            _str_kv("rule.name", alert.rule_name),
            _str_kv("entity.uuid", alert.entity_uuid),
            _str_kv("entity.value", alert.entity_value),
            _str_kv("entity.type", alert.entity_type),
            _double_kv("risk.score", alert.risk_score),
            _str_array_kv("mitre.tactics", alert.mitre_tactics),
            _str_array_kv("mitre.techniques", alert.mitre_techniques),
            _str_kv("dedup.key", alert.dedup_key),
            _int_kv("dedup.count", alert.dedup_count),
            _str_array_kv(
                "contributing.event_ids",
                tuple(str(e) for e in alert.contributing_events),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Batch construction
# ---------------------------------------------------------------------------


def _get_version() -> str:
    """Return the seerflow package version, or 'dev' if not installed."""
    try:
        return importlib.metadata.version("seerflow")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def build_export_request(alerts: list[Alert]) -> ExportLogsServiceRequest:
    """Build an ExportLogsServiceRequest from a list of alerts.

    All alerts share a single ResourceLogs and ScopeLogs wrapper.
    Raises ValueError if alerts is empty.
    """
    if not alerts:
        raise ValueError("Cannot build export request from empty alert list")

    version = _get_version()
    resource = Resource(
        attributes=[
            _str_kv("service.name", "seerflow"),
            _str_kv("service.version", version),
        ],
    )
    scope = InstrumentationScope(name="seerflow.alerting", version=version)
    log_records = [alert_to_log_record(a) for a in alerts]
    return ExportLogsServiceRequest(
        resource_logs=[
            ResourceLogs(
                resource=resource,
                scope_logs=[
                    ScopeLogs(scope=scope, log_records=log_records),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------


def _normalize_grpc_endpoint(endpoint: str) -> str:
    """Strip http:// or https:// scheme for gRPC channels (they take host:port)."""
    for prefix in ("https://", "http://"):
        if endpoint.startswith(prefix):
            return endpoint[len(prefix) :]
    return endpoint


def _resolve_tls(endpoint: str, tls: bool | None) -> bool:
    """Resolve effective TLS usage for a gRPC OTLP endpoint.

    Explicit ``tls`` wins; otherwise auto-detect from scheme.
    Bare ``host:port`` defaults to plaintext for backward compatibility.
    """
    if tls is not None:
        return tls
    return endpoint.startswith("https://")


def masked_url(url: str) -> str:
    """Mask an endpoint URL to avoid logging sensitive paths.

    Handles both scheme-prefixed URLs (http://host:port) and bare
    host:port endpoints used by gRPC.
    """
    parsed = urlparse(url)
    if parsed.hostname:
        scheme = parsed.scheme or "grpc"
        return f"{scheme}://{parsed.hostname}/***"
    # Bare host:port (no scheme) — urlparse puts everything in 'scheme'
    host = url.split("/")[0].split(":")[0]
    if host:
        return f"grpc://{host}/***"
    return "<invalid-url>"


# ---------------------------------------------------------------------------
# OtlpSink
# ---------------------------------------------------------------------------


class OtlpSink:
    """Async batch sink that exports alerts as OTLP log records.

    Usage::

        sink = OtlpSink(endpoint="localhost:4317", protocol="grpc")
        asyncio.create_task(sink.run())
        sink.enqueue(alert)
        await sink.stop()
    """

    _MAX_RETRIES = 3
    _RETRY_DELAYS = (1.0, 2.0, 4.0)

    def __init__(
        self,
        endpoint: str,
        protocol: Literal["grpc", "http"],
        export_interval: int = 5,
        max_pending: int = 10_000,
        *,
        tls: bool | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._protocol = protocol
        self._export_interval = export_interval
        self._max_pending = max_pending
        self._use_tls = _resolve_tls(endpoint, tls)
        self._pending: asyncio.Queue[Alert] = asyncio.Queue(maxsize=max_pending)
        self._stop_event: asyncio.Event = asyncio.Event()
        self._grpc_channel: grpc.aio.Channel | None = None
        self._http_session: aiohttp.ClientSession | None = None
        if tls is False and endpoint.startswith("https://"):
            _log.warning(
                "OTLP sink: otlp_tls=False but endpoint scheme is https (%s) "
                "— scheme/override mismatch, using plaintext",
                masked_url(endpoint),
            )

    def enqueue(self, alert: Alert) -> None:
        """Add an alert to the pending queue. Drops with warning if full."""
        try:
            self._pending.put_nowait(alert)
        except QueueFull:
            _log.warning(
                "OTLP sink pending queue full — dropping alert %s",
                alert.alert_id,
            )

    async def run(self) -> None:
        """Background loop: wait for interval or stop signal, then flush."""
        try:
            while not self._stop_event.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._export_interval,
                    )
                await self._flush()
        finally:
            # Drain any alerts enqueued between last flush and cancellation.
            await self._flush()

    async def stop(self) -> None:
        """Signal the sink to stop. ``run()`` will flush and exit."""
        self._stop_event.set()

    async def close(self) -> None:
        """Close transport resources."""
        if self._grpc_channel is not None:
            await self._grpc_channel.close()
            self._grpc_channel = None
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None

    async def _flush(self) -> None:
        """Drain the pending queue and send as a single batch."""
        batch: list[Alert] = []
        while True:
            try:
                batch.append(self._pending.get_nowait())
            except QueueEmpty:
                break
        if not batch:
            return
        batch_size = len(batch)
        try:
            request = build_export_request(batch)
            if self._protocol == "grpc":
                await self._send_grpc(request, batch_size)
            else:
                await self._send_http(request, batch_size)
        except Exception:
            _log.exception(
                "OTLP flush failed, dropping %d alerts",
                len(batch),
            )

    async def _send_grpc(self, request: ExportLogsServiceRequest, batch_size: int) -> None:
        """Send batch via gRPC with retry."""
        import grpc

        if self._grpc_channel is None:
            target = _normalize_grpc_endpoint(self._endpoint)
            if self._use_tls:
                creds = grpc.ssl_channel_credentials()
                self._grpc_channel = grpc.aio.secure_channel(target, creds)
            else:
                self._grpc_channel = grpc.aio.insecure_channel(target)
        stub = LogsServiceStub(self._grpc_channel)  # type: ignore[no-untyped-call]
        for attempt in range(self._MAX_RETRIES):
            try:
                await stub.Export(request)
                return
            except grpc.RpcError as exc:
                code = exc.code() if hasattr(exc, "code") else None
                _log.warning(
                    "OTLP gRPC export to %s failed (attempt %d): %s (code=%s)",
                    masked_url(self._endpoint),
                    attempt + 1,
                    exc.details() if hasattr(exc, "details") else str(exc),
                    code,
                )
            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        _log.error(
            "OTLP gRPC export to %s: all %d retries exhausted, dropping %d alerts",
            masked_url(self._endpoint),
            self._MAX_RETRIES,
            batch_size,
        )

    async def _send_http(self, request: ExportLogsServiceRequest, batch_size: int) -> None:
        """Send batch via HTTP POST with retry."""
        if self._http_session is None:
            self._http_session = aiohttp.ClientSession()
        url = f"{self._endpoint.rstrip('/')}/v1/logs"
        body = request.SerializeToString()
        headers = {"Content-Type": "application/x-protobuf"}
        for attempt in range(self._MAX_RETRIES):
            try:
                async with self._http_session.post(
                    url,
                    data=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                ) as resp:
                    if resp.status < 400:
                        return
                    if resp.status < 500:
                        _log.error(
                            "OTLP HTTP export to %s returned %d — not retrying",
                            masked_url(self._endpoint),
                            resp.status,
                        )
                        return
                    _log.warning(
                        "OTLP HTTP export to %s returned %d (attempt %d)",
                        masked_url(self._endpoint),
                        resp.status,
                        attempt + 1,
                    )
            except Exception as exc:
                _log.warning(
                    "OTLP HTTP export to %s failed (attempt %d): %s",
                    masked_url(self._endpoint),
                    attempt + 1,
                    exc,
                )
            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        _log.error(
            "OTLP HTTP export to %s: all %d retries exhausted, dropping %d alerts",
            masked_url(self._endpoint),
            self._MAX_RETRIES,
            batch_size,
        )
