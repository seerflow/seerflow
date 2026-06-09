"""Integration: the syslog sink ships RFC 5424 frames over real sockets and
registers on the NotificationRouter through the existing dispatch path
(S-363/FR-002).

Uses ephemeral OS-assigned ports and real loopback UDP/TCP listeners to assert
the on-the-wire framing (correct PRI = facility*8 + severity, VERSION, BOM MSG).
"""

from __future__ import annotations

import asyncio
import re
import socket
import uuid

import pytest

from seerflow.alerting.router import (
    DefaultRouting,
    NotificationRouter,
    RoutingRule,
    RoutingRuleMatch,
    RoutingRuleNotify,
)
from seerflow.alerting.sinks.registry import build_sink
from seerflow.config import SinkConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel

_PRI_RE = re.compile(rb"^<(\d+)>1 ")


def _alert(severity: SeverityLevel = SeverityLevel.ERROR) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity,
        rule_name="r-int",
        description="routed via syslog sink",
        entity_uuid="e-1",
        entity_value="10.0.0.9",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        risk_score=0.99,
        dedup_key="int:r",
    )


# ---------------------------------------------------------------------------
# UDP over a real loopback socket
# ---------------------------------------------------------------------------


async def test_udp_frame_delivered_over_real_socket() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(5.0)
    port = listener.getsockname()[1]
    try:
        sink = build_sink(
            SinkConfig(
                type="syslog",
                name="udp-sink",
                formatter="cef",
                options=(
                    ("host", "127.0.0.1"),
                    ("port", str(port)),
                    ("facility", "16"),
                    ("transport", "udp"),
                ),
            )
        )
        await sink.deliver(_alert(SeverityLevel.ERROR))
        data, _ = await asyncio.to_thread(listener.recvfrom, 65535)
    finally:
        listener.close()

    match = _PRI_RE.match(data)
    assert match is not None
    # facility 16 (local0) * 8 + severity 3 (error) = 131.
    assert int(match.group(1)) == 131
    # BOM-prefixed CEF MSG carried in the frame.
    assert b"\xef\xbb\xbfCEF:0|Seerflow|Seerflow|" in data


# ---------------------------------------------------------------------------
# TCP over a real loopback server (octet-counted framing)
# ---------------------------------------------------------------------------


async def test_tcp_frame_delivered_over_real_server() -> None:
    received: list[bytes] = []
    ready = asyncio.Event()

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        chunk = await reader.read(65535)
        received.append(chunk)
        writer.close()
        ready.set()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    sink = build_sink(
        SinkConfig(
            type="syslog",
            name="tcp-sink",
            formatter="json",
            options=(
                ("host", "127.0.0.1"),
                ("port", str(port)),
                ("facility", "1"),
                ("transport", "tcp"),
            ),
        )
    )
    try:
        await sink.deliver(_alert(SeverityLevel.CRITICAL))
        await asyncio.wait_for(ready.wait(), timeout=5.0)
    finally:
        await sink.close()
        server.close()
        await server.wait_closed()

    assert sink.failure_count == 0  # type: ignore[attr-defined]
    payload = received[0]
    # RFC 6587 octet-counting prefix: "<len> <frame>".
    length, _, frame = payload.partition(b" ")
    assert int(length) == len(frame)
    match = _PRI_RE.match(frame)
    assert match is not None
    # facility 1 (user) * 8 + severity 2 (critical) = 10.
    assert int(match.group(1)) == 10


# ---------------------------------------------------------------------------
# Router registration through the existing dispatch path
# ---------------------------------------------------------------------------


async def test_declared_syslog_sink_receives_routed_alert() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(5.0)
    port = listener.getsockname()[1]
    try:
        target = build_sink(
            SinkConfig(
                type="syslog",
                name="ops-syslog",
                formatter="json",
                options=(("host", "127.0.0.1"), ("port", str(port)), ("transport", "udp")),
            )
        )
        router = NotificationRouter(
            targets=(),
            rules=(
                RoutingRule(
                    match=RoutingRuleMatch(),
                    notify=(RoutingRuleNotify(channel="ops-syslog", mode="immediate"),),
                ),
            ),
            default_routing=DefaultRouting(action="drop"),
        )
        router.register_target(target)
        await router.route(_alert())
        data, _ = await asyncio.to_thread(listener.recvfrom, 65535)
    finally:
        listener.close()

    assert _PRI_RE.match(data) is not None
    assert b"r-int" in data


# ---------------------------------------------------------------------------
# Unreachable collector — failure counted, pipeline never blocked
# ---------------------------------------------------------------------------


async def test_tcp_unreachable_collector_does_not_raise() -> None:
    # Bind+close to obtain a port nothing is listening on.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    sink = build_sink(
        SinkConfig(
            type="syslog",
            name="dead-tcp",
            formatter="json",
            options=(("host", "127.0.0.1"), ("port", str(dead_port)), ("transport", "tcp")),
        )
    )
    sink._retry_delays = (0.0,)  # type: ignore[attr-defined]
    sink._attempts = 2  # type: ignore[attr-defined]
    # Must not raise even though the collector is unreachable.
    await sink.deliver(_alert())
    assert sink.failure_count == 1  # type: ignore[attr-defined]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
