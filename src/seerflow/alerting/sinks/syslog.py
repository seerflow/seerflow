"""Outbound syslog sink (RFC 5424 over UDP/TCP) (S-363/FR-002).

A :class:`~seerflow.alerting.target.DeliveryTarget` that ships alerts to any
syslog-compatible collector. Each alert is rendered as a single RFC 5424 frame:

    <PRI>VERSION SP TIMESTAMP SP HOSTNAME SP APP-NAME SP PROCID SP MSGID SP
    STRUCTURED-DATA SP MSG

- ``PRI = facility*8 + severity``. ``facility`` is configurable (default 1,
  user-level); ``severity`` is derived per-alert from the Seerflow
  ``SeverityLevel`` via an explicit inverse of the receiver's mapping table.
- ``VERSION`` is ``1``; ``PROCID``/``MSGID``/``STRUCTURED-DATA`` are NILVALUE
  (``-``); ``MSG`` is a BOM-prefixed UTF-8 payload (RFC 5424 §6.4) rendered by
  the per-sink formatter (S-361): ``cef``/``leef`` produce a single line, every
  other token collapses to compact ``format_json`` JSON.

Transports (selectable via config):
- **UDP** — one connected datagram per frame. Send failures are *counted*
  (:attr:`SyslogSink.failure_count`) and swallowed; a transport error can never
  block or crash the pipeline.
- **TCP** — RFC 6587 octet-counted framing (``MSG-LEN SP FRAME``) over a
  persistent connection. Send errors are *retried* with bounded backoff
  (reconnecting between attempts); a persistent failure is counted, never raised.

All blocking socket I/O runs in a worker thread (:func:`asyncio.to_thread`) so
the event loop is never stalled. This is the OUTBOUND sink — distinct from the
INBOUND ``seerflow.receivers.syslog`` receiver.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from seerflow.alerting.formatters import format_cef, format_json, format_leef
from seerflow.alerting.target import loop_deliver_digest
from seerflow.models.event import SeverityLevel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert

_log = logging.getLogger(__name__)

# RFC 5424 constants.
_SYSLOG_VERSION = "1"
_NILVALUE = "-"
_BOM = "﻿"

# Sensible transport defaults (overridable via config).
_DEFAULT_UDP_PORT = 514
_DEFAULT_FACILITY = 1  # user-level messages
_DEFAULT_TRANSPORT: Literal["udp", "tcp"] = "udp"
_DEFAULT_ATTEMPTS = 3
_DEFAULT_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0)
_SOCKET_TIMEOUT_SECONDS = 5.0

_VALID_TRANSPORTS: frozenset[str] = frozenset({"udp", "tcp"})

# Compact JSON separators so the MSG payload stays single-line and tight.
_COMPACT_SEPARATORS = (",", ":")

# Seerflow SeverityLevel (0..6) -> syslog severity (0..7). Explicit inverse of
# the receiver's ``_SYSLOG_TO_SEERFLOW`` table — no arithmetic guesswork, every
# level is conformance-tested. Syslog: 1=Alert .. 7=Debug.
_SEERFLOW_TO_SYSLOG: dict[SeverityLevel, int] = {
    SeverityLevel.TRACE: 7,  # Debug
    SeverityLevel.INFORMATIONAL: 6,  # Informational
    SeverityLevel.NOTICE: 5,  # Notice
    SeverityLevel.WARNING: 4,  # Warning
    SeverityLevel.ERROR: 3,  # Error
    SeverityLevel.CRITICAL: 2,  # Critical
    SeverityLevel.FATAL: 1,  # Alert
}


def _syslog_severity(level: SeverityLevel) -> int:
    """Map a Seerflow ``SeverityLevel`` onto a syslog severity (0..7)."""
    return _SEERFLOW_TO_SYSLOG.get(level, 5)


def _compute_pri(facility: int, alert: Alert) -> int:
    """Return the RFC 5424 priority value ``facility*8 + severity``."""
    return facility * 8 + _syslog_severity(alert.severity_id)


def _render_message(alert: Alert, formatter: str) -> str:
    """Render the MSG body for ``alert`` using the selected formatter token.

    ``cef``/``leef`` emit a single line; every other token (``json`` and the
    dict-only ``slack``/``teams``) collapses to compact ``format_json`` JSON —
    matching the queue-sink adapter's "any non-line token renders JSON" rule.
    """
    if formatter == "cef":
        return format_cef(alert)
    if formatter == "leef":
        return format_leef(alert)
    return json.dumps(format_json(alert), separators=_COMPACT_SEPARATORS)


def _rfc3339(timestamp_ns: int) -> str:
    """Convert a nanosecond epoch timestamp to an RFC 3339 UTC string."""
    return datetime.fromtimestamp(timestamp_ns / 1e9, tz=UTC).isoformat().replace("+00:00", "Z")


def _build_frame(
    alert: Alert,
    *,
    facility: int,
    hostname: str,
    app_name: str,
    formatter: str,
) -> bytes:
    """Build a single RFC 5424 syslog frame for ``alert`` as UTF-8 bytes."""
    pri = _compute_pri(facility, alert)
    header = (
        f"<{pri}>{_SYSLOG_VERSION} {_rfc3339(alert.timestamp_ns)} "
        f"{hostname} {app_name} {_NILVALUE} {_NILVALUE} {_NILVALUE} "
    )
    message = f"{_BOM}{_render_message(alert, formatter)}"
    return (header + message).encode("utf-8")


def _octet_counted(frame: bytes) -> bytes:
    """Wrap a frame in RFC 6587 octet-counting framing: ``<len> <frame>``."""
    return f"{len(frame)} ".encode("ascii") + frame


class SyslogSink:
    """Outbound sink that ships Seerflow alerts to a syslog collector.

    Satisfies the :class:`~seerflow.alerting.target.DeliveryTarget` protocol
    structurally (read-only ``name``/``min_severity`` properties + async
    ``deliver``/``deliver_digest``).

    Like the other delivery targets, a single sink instance assumes
    single-flight delivery: the ``NotificationRouter`` drives ``deliver`` for a
    given target sequentially, so the persistent TCP socket and
    ``failure_count`` need no cross-thread locking even though socket I/O is
    offloaded to a worker thread.
    """

    def __init__(
        self,
        *,
        host: str,
        name: str,
        port: int = _DEFAULT_UDP_PORT,
        facility: int = _DEFAULT_FACILITY,
        transport: str = _DEFAULT_TRANSPORT,
        hostname: str = "",
        app_name: str = "seerflow",
        formatter: str = "json",
        min_severity: int = 0,
        attempts: int = _DEFAULT_ATTEMPTS,
        retry_delays: tuple[float, ...] = _DEFAULT_RETRY_DELAYS,
    ) -> None:
        if not host:
            msg = "syslog sink requires a non-empty host"
            raise ValueError(msg)
        if transport not in _VALID_TRANSPORTS:
            msg = f"syslog transport must be one of {sorted(_VALID_TRANSPORTS)}, got {transport!r}"
            raise ValueError(msg)
        self._host = host
        self._port = port
        self._facility = facility
        self._transport = transport
        # Default hostname to the local machine name; never crash on lookup.
        self._hostname = hostname or socket.gethostname() or _NILVALUE
        self._app_name = app_name
        self._formatter = formatter
        self._name = name
        self._min_severity = min_severity
        self._attempts = attempts
        self._retry_delays = retry_delays
        self._tcp_socket: socket.socket | None = None
        self.failure_count = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def min_severity(self) -> int:
        return self._min_severity

    def _frame(self, alert: Alert) -> bytes:
        return _build_frame(
            alert,
            facility=self._facility,
            hostname=self._hostname,
            app_name=self._app_name,
            formatter=self._formatter,
        )

    async def deliver(self, alert: Alert) -> None:
        """Ship a single alert as one RFC 5424 frame (never blocks/raises)."""
        frame = self._frame(alert)
        if self._transport == "udp":
            await asyncio.to_thread(self._send_udp, frame)
        else:
            await asyncio.to_thread(self._send_tcp, frame)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        """Deliver each alert as its own frame (default per-alert loop)."""
        if not alerts:
            return
        await loop_deliver_digest(self, alerts)

    async def close(self) -> None:
        """Release the persistent TCP socket if one is open."""
        await asyncio.to_thread(self._close_tcp)

    # ------------------------------------------------------------------
    # UDP transport — failures counted, never raised.
    # ------------------------------------------------------------------

    def _open_udp_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(_SOCKET_TIMEOUT_SECONDS)
        sock.connect((self._host, self._port))
        return sock

    def _send_udp(self, frame: bytes) -> None:
        sock: socket.socket | None = None
        try:
            sock = self._open_udp_socket()
            sock.send(frame)
        except OSError as exc:
            self.failure_count += 1
            _log.warning("syslog UDP send to %s:%d failed: %s", self._host, self._port, exc)
        finally:
            if sock is not None:
                sock.close()

    # ------------------------------------------------------------------
    # TCP transport — errors retried, persistent failure counted, never raised.
    # ------------------------------------------------------------------

    def _open_tcp_socket(self) -> socket.socket:
        return socket.create_connection((self._host, self._port), timeout=_SOCKET_TIMEOUT_SECONDS)

    def _close_tcp(self) -> None:
        if self._tcp_socket is not None:
            # Close errors are non-fatal — the socket is being discarded anyway.
            with contextlib.suppress(OSError):
                self._tcp_socket.close()
            self._tcp_socket = None

    def _send_tcp(self, frame: bytes) -> None:
        payload = _octet_counted(frame)
        last_exc: OSError | None = None
        for attempt in range(self._attempts):
            try:
                self._tcp_send_once(payload)
            except OSError as exc:
                last_exc = exc
                self._close_tcp()
                self._sleep_before_retry(attempt)
            else:
                return
        self.failure_count += 1
        _log.warning(
            "syslog TCP send to %s:%d failed after %d attempts: %s",
            self._host,
            self._port,
            self._attempts,
            last_exc,
        )

    def _tcp_send_once(self, payload: bytes) -> None:
        if self._tcp_socket is None:
            self._tcp_socket = self._open_tcp_socket()
        self._tcp_socket.sendall(payload)

    def _sleep_before_retry(self, attempt: int) -> None:
        if attempt >= self._attempts - 1 or not self._retry_delays:
            return
        delay = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
        if delay > 0:
            time.sleep(delay)
