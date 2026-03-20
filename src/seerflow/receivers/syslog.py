"""Syslog UDP/TCP receiver — RFC 5424 + 3164."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)

_PRIORITY_RE = re.compile(rb"^<(\d{1,3})>(.*)$", re.DOTALL)


def _parse_priority(data: bytes) -> tuple[int, int, bytes]:
    """Extract facility and severity from syslog priority.

    Returns (facility, severity, rest) where rest is the message after the
    priority tag. If no priority is found, defaults to user.notice (1, 5).
    """
    match = _PRIORITY_RE.match(data)
    if not match:
        return 1, 5, data  # default: user.notice
    priority = int(match.group(1))
    facility = priority >> 3
    severity = priority & 0x07
    return facility, severity, match.group(2)


def _detect_rfc_version(rest: bytes) -> str:
    """Detect RFC 5424 vs 3164 based on first byte after priority.

    RFC 5424 messages start with a version digit (e.g. ``1 ...``).
    Everything else is treated as RFC 3164.
    """
    if rest and rest[0:1].isdigit():
        return "5424"
    return "3164"


_SYSLOG_TO_SEERFLOW = (6, 5, 5, 4, 3, 2, 1, 0)


def _map_severity(syslog_severity: int) -> int:
    """Map syslog severity (0-7) to SeerflowEvent severity_id (0-6).

    Syslog: 0=Emergency, 1=Alert, 2=Critical, 3=Error, 4=Warning,
            5=Notice, 6=Informational, 7=Debug
    Seerflow: 0=TRACE, 1=INFORMATIONAL, 2=NOTICE, 3=WARNING, 4=ERROR,
              5=CRITICAL, 6=FATAL
    """
    return _SYSLOG_TO_SEERFLOW[min(syslog_severity, 7)]


def _parse_syslog(data: bytes, remote_addr: str, protocol: str) -> RawEvent:
    """Parse a syslog message into a RawEvent.

    The ``source_id`` field is left empty — the caller (SyslogReceiver)
    fills it from its own configuration.
    """
    facility, severity, rest = _parse_priority(data)
    rfc = _detect_rfc_version(rest)
    return RawEvent(
        data=data,
        source_type="syslog",
        source_id="",
        received_ns=time.time_ns(),
        metadata={
            "remote_addr": remote_addr,
            "protocol": protocol,
            "facility": facility,
            "severity": severity,
            "seerflow_severity": _map_severity(severity),
            "rfc_version": rfc,
        },
    )


class _SyslogUDPProtocol(asyncio.DatagramProtocol):
    """Asyncio datagram protocol that parses syslog and enqueues RawEvents."""

    def __init__(self, manager: ReceiverManager, source_id: str) -> None:
        self._manager = manager
        self._source_id = source_id

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        event = _parse_syslog(data, addr[0], "udp")
        event = RawEvent(
            data=event.data,
            source_type=event.source_type,
            source_id=self._source_id,
            received_ns=event.received_ns,
            metadata=event.metadata,
        )
        asyncio.get_running_loop().create_task(self._manager.put_event(event))


class SyslogReceiver:
    """Syslog receiver supporting UDP and TCP (RFC 5424 + 3164).

    Use ``udp_port=0`` and ``tcp_port=0`` in tests to let the OS assign
    ephemeral ports. Read the actual ports via the ``udp_port`` and
    ``tcp_port`` properties after ``start()``.
    """

    __slots__ = (
        "_bind_addr",
        "_manager",
        "_source_id",
        "_started",
        "_stopped",
        "_tcp_enabled",
        "_tcp_port_config",
        "_tcp_server",
        "_udp_enabled",
        "_udp_port_config",
        "_udp_transport",
    )

    def __init__(
        self,
        manager: ReceiverManager,
        *,
        source_id: str,
        bind_addr: str = "0.0.0.0",  # noqa: S104  # nosec B104 — syslog receiver must listen on all interfaces
        udp_port: int = 514,
        tcp_port: int = 601,
        udp_enabled: bool = True,
        tcp_enabled: bool = True,
    ) -> None:
        self._manager = manager
        self._source_id = source_id
        self._bind_addr = bind_addr
        self._udp_port_config = udp_port
        self._tcp_port_config = tcp_port
        self._udp_enabled = udp_enabled
        self._tcp_enabled = tcp_enabled
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tcp_server: asyncio.Server | None = None
        self._started = False
        self._stopped = False

    async def start(self) -> None:
        """Start listening on configured UDP and/or TCP sockets."""
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        if self._udp_enabled:
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: _SyslogUDPProtocol(self._manager, self._source_id),
                local_addr=(self._bind_addr, self._udp_port_config),
            )
            self._udp_transport = transport
        if self._tcp_enabled:
            self._tcp_server = await asyncio.start_server(
                self._handle_tcp_client,
                self._bind_addr,
                self._tcp_port_config,
            )

    async def _handle_tcp_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single TCP client connection with newline framing."""
        addr = writer.get_extra_info("peername")
        remote = addr[0] if addr else "unknown"
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                stripped = line.rstrip(b"\n\r")
                if not stripped:
                    continue
                event = _parse_syslog(stripped, remote, "tcp")
                event = RawEvent(
                    data=event.data,
                    source_type=event.source_type,
                    source_id=self._source_id,
                    received_ns=event.received_ns,
                    metadata=event.metadata,
                )
                await self._manager.put_event(event)
        except ConnectionError:
            _log.debug("TCP client %s disconnected", remote)
        finally:
            writer.close()

    async def stop(self) -> None:
        """Stop all listeners."""
        if self._stopped:
            return
        self._stopped = True
        if self._udp_transport is not None:
            self._udp_transport.close()
        if self._tcp_server is not None:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()

    def is_healthy(self) -> bool:
        """Return True if the receiver has started and not been stopped."""
        return self._started and not self._stopped

    @property
    def udp_port(self) -> int:
        """Actual bound UDP port (useful when configured with port=0)."""
        if self._udp_transport is not None:
            sockname = self._udp_transport.get_extra_info("sockname")
            if sockname:
                return int(sockname[1])
        return self._udp_port_config

    @property
    def tcp_port(self) -> int:
        """Actual bound TCP port (useful when configured with port=0)."""
        if self._tcp_server is not None:
            sockets = self._tcp_server.sockets
            if sockets:
                return int(sockets[0].getsockname()[1])
        return self._tcp_port_config
