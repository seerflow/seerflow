"""Adapt queue-backed sinks (Console/File) to the DeliveryTarget protocol.

The router drives ``deliver`` directly via the existing dispatch path; the
adapter does NOT start a second queue/consumer loop, so no parallel dispatch
path is introduced (S-361 AC-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Literal, Protocol

from seerflow.alerting.target import loop_deliver_digest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.alerting.sinks.hec import HecSink
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.syslog import SyslogSink
    from seerflow.config import SinkConfig
    from seerflow.models.alert import Alert


class _WritableSink(Protocol):
    """Structural type for the queue-backed sinks we adapt."""

    def _write_alert(self, alert: Alert) -> None: ...  # pragma: no cover


@dataclass(frozen=True, slots=True)
class _QueueSinkDeliveryAdapter:
    """Expose a ``_write_alert``-based sink as a ``DeliveryTarget``."""

    name: str
    min_severity: int
    _sink: _WritableSink = field(repr=False)

    async def deliver(self, alert: Alert) -> None:
        self._sink._write_alert(alert)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        await loop_deliver_digest(self, alerts)


def _build_console_sink(config: SinkConfig, stream_override: IO[str] | None) -> _WritableSink:
    from seerflow.alerting.sinks.console import ConsoleSink

    opts = dict(config.options)
    stream = stream_override if stream_override is not None else opts.get("stream", "stdout")
    # ConsoleSink renders human|json only. The config-layer formatter token set
    # (slack|teams|json) is wider because it is shared with webhook transports;
    # for a console sink any non-json token renders as the human line. Richer
    # per-transport formatter resolution arrives with the HEC/CEF/LEEF sinks.
    fmt: Literal["human", "json"] = "json" if config.formatter == "json" else "human"
    return ConsoleSink(
        stream,  # type: ignore[arg-type]
        fmt=fmt,
        min_severity=config.min_severity,
    )


def _build_file_sink(config: SinkConfig) -> _WritableSink:
    from seerflow.alerting.sinks.file import FileSink

    path = dict(config.options).get("path", "")
    if not path:
        msg = "file sink requires options.path"
        raise ValueError(msg)
    return FileSink(path, min_severity=config.min_severity)


def build_queue_sink_target(
    config: SinkConfig,
    *,
    _stream_override: IO[str] | None = None,
) -> _QueueSinkDeliveryAdapter:
    """Build a DeliveryTarget for a ``console``/``file`` SinkConfig."""
    if config.type == "console":
        sink = _build_console_sink(config, _stream_override)
    elif config.type == "file":
        sink = _build_file_sink(config)
    else:  # pragma: no cover - registry guards this
        msg = f"unsupported queue sink type {config.type!r}"
        raise ValueError(msg)
    return _QueueSinkDeliveryAdapter(
        name=config.name, min_severity=config.min_severity, _sink=sink
    )


@dataclass(frozen=True, slots=True)
class _OtlpSinkDeliveryAdapter:
    """Expose an :class:`OtlpSink` as a ``DeliveryTarget`` (S-366).

    ``deliver`` enqueues onto the sink's existing batch queue; the sink's own
    ``run()`` loop performs the export. No second consumer loop is started, so
    no parallel dispatch path is introduced (mirrors S-361's queue-sink adapter).
    """

    name: str
    min_severity: int
    _sink: OtlpSink = field(repr=False)

    async def deliver(self, alert: Alert) -> None:
        self._sink.enqueue(alert)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        await loop_deliver_digest(self, alerts)


def build_otlp_sink_target(config: SinkConfig) -> _OtlpSinkDeliveryAdapter:
    """Build a DeliveryTarget for an ``otlp`` SinkConfig.

    Reads transport options from ``config.options``: ``endpoint`` (required),
    ``protocol`` (``grpc``|``http``, default ``grpc``). Auth headers are sourced
    from env-backed config at the top-level ``alerting.otlp_headers`` rather than
    per-sink options, so the registry path does not duplicate secret plumbing.
    """
    from seerflow.alerting.sinks.otlp import OtlpSink

    opts = dict(config.options)
    endpoint = opts.get("endpoint", "")
    if not endpoint:
        msg = "otlp sink requires options.endpoint"
        raise ValueError(msg)
    protocol: Literal["grpc", "http"] = "http" if opts.get("protocol") == "http" else "grpc"
    sink = OtlpSink(endpoint=endpoint, protocol=protocol)
    return _OtlpSinkDeliveryAdapter(name=config.name, min_severity=config.min_severity, _sink=sink)


def build_hec_sink_target(config: SinkConfig) -> HecSink:
    """Build a Splunk HEC ``DeliveryTarget`` for a ``hec`` SinkConfig (S-362).

    Reads transport options from ``config.options``: ``endpoint`` (required base
    URL), ``token`` (required HEC token — env-sourced upstream, never hardcoded),
    and ``ca`` (optional CA-bundle path for a private collector). The token is
    held only in the sink's auth header and never logged. ``HecSink`` itself
    satisfies the ``DeliveryTarget`` protocol, so no wrapping adapter is needed.

    Raises ``ValueError`` for a missing endpoint/token (config-layer validation
    should reject these first; this is the defence-in-depth fallback).
    """
    from seerflow.alerting.sinks.hec import HecSink

    opts = dict(config.options)
    endpoint = opts.get("endpoint", "")
    if not endpoint:
        msg = "hec sink requires options.endpoint"
        raise ValueError(msg)
    token = opts.get("token", "")
    if not token:
        msg = "hec sink requires options.token"
        raise ValueError(msg)
    return HecSink(
        endpoint,
        token,
        name=config.name,
        min_severity=config.min_severity,
        ca=opts.get("ca", ""),
    )


# Syslog transport option defaults. Stable string defaults mirror the values the
# config-layer validator injects, so the registry path stays consistent whether
# a sink is built from validated config or directly in a test.
_SYSLOG_DEFAULT_PORT = "514"
_SYSLOG_DEFAULT_FACILITY = "1"
_SYSLOG_DEFAULT_TRANSPORT = "udp"


def build_syslog_sink_target(config: SinkConfig) -> SyslogSink:
    """Build an RFC 5424 syslog ``DeliveryTarget`` for a ``syslog`` SinkConfig (S-363).

    Reads transport options from ``config.options``: ``host`` (required),
    ``port`` (default 514), ``facility`` (default 1), ``transport``
    (``udp``|``tcp``, default ``udp``). The sink's per-frame formatter is
    ``config.formatter`` (``cef``/``leef`` → line; others → JSON). ``SyslogSink``
    itself satisfies ``DeliveryTarget``, so no wrapping adapter is needed.

    Raises ``ValueError`` for a missing host (config-layer validation should
    reject it first; this is the defence-in-depth fallback).
    """
    from seerflow.alerting.sinks.syslog import SyslogSink

    opts = dict(config.options)
    host = opts.get("host", "")
    if not host:
        msg = "syslog sink requires options.host"
        raise ValueError(msg)
    return SyslogSink(
        host=host,
        name=config.name,
        port=int(opts.get("port", _SYSLOG_DEFAULT_PORT)),
        facility=int(opts.get("facility", _SYSLOG_DEFAULT_FACILITY)),
        transport=opts.get("transport", _SYSLOG_DEFAULT_TRANSPORT),
        formatter=config.formatter,
        min_severity=config.min_severity,
    )
