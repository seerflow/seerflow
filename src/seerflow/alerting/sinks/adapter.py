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
