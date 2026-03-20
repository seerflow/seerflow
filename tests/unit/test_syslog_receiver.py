"""Tests for SyslogReceiver — parsing, severity, UDP, TCP."""

from __future__ import annotations

import asyncio
import socket

import pytest

from seerflow.receivers.base import Receiver
from seerflow.receivers.manager import ReceiverManager
from seerflow.receivers.syslog import (
    SyslogReceiver,
    _detect_rfc_version,
    _map_severity,
    _parse_priority,
    _parse_syslog,
)


class TestSyslogParsing:
    def test_parse_priority(self) -> None:
        facility, severity, rest = _parse_priority(b"<165>1 2026-03-20T04:00:00Z host app - - - msg")
        assert facility == 20
        assert severity == 5
        assert rest.startswith(b"1 ")

    def test_parse_priority_low(self) -> None:
        facility, severity, rest = _parse_priority(b"<0>emergency message")
        assert facility == 0
        assert severity == 0

    def test_parse_priority_missing_returns_defaults(self) -> None:
        facility, severity, rest = _parse_priority(b"no priority here")
        assert facility == 1  # user
        assert severity == 5  # notice
        assert rest == b"no priority here"

    def test_detect_rfc5424(self) -> None:
        assert _detect_rfc_version(b"1 2026-03-20T04:00:00Z host app") == "5424"

    def test_detect_rfc3164(self) -> None:
        assert _detect_rfc_version(b"Mar 20 04:00:00 myhost sshd") == "3164"

    def test_detect_unknown_defaults_to_3164(self) -> None:
        assert _detect_rfc_version(b"random garbage") == "3164"

    def test_parse_syslog_rfc5424(self) -> None:
        data = b"<165>1 2026-03-20T04:00:00.000Z myhost myapp 1234 ID47 - Login failed"
        event = _parse_syslog(data, "192.168.1.1", "udp")
        assert event.source_type == "syslog"
        assert event.data == data
        assert event.metadata["remote_addr"] == "192.168.1.1"
        assert event.metadata["protocol"] == "udp"
        assert event.metadata["facility"] == 20
        assert event.metadata["severity"] == 5

    def test_parse_syslog_rfc3164(self) -> None:
        data = b"<34>Mar 20 04:00:00 myhost sshd[1234]: Login failed"
        event = _parse_syslog(data, "10.0.0.1", "tcp")
        assert event.source_type == "syslog"
        assert event.metadata["facility"] == 4
        assert event.metadata["severity"] == 2
        assert event.metadata["protocol"] == "tcp"


class TestSeverityMapping:
    def test_emergency(self) -> None:
        assert _map_severity(0) == 6  # FATAL

    def test_alert(self) -> None:
        assert _map_severity(1) == 5  # CRITICAL

    def test_critical(self) -> None:
        assert _map_severity(2) == 5  # CRITICAL

    def test_error(self) -> None:
        assert _map_severity(3) == 4  # ERROR

    def test_warning(self) -> None:
        assert _map_severity(4) == 3  # WARNING

    def test_notice(self) -> None:
        assert _map_severity(5) == 2  # NOTICE

    def test_info(self) -> None:
        assert _map_severity(6) == 1  # INFORMATIONAL

    def test_debug(self) -> None:
        assert _map_severity(7) == 0  # TRACE

    def test_parse_syslog_includes_seerflow_severity(self) -> None:
        data = b"<165>1 2026-03-20T04:00:00Z host app - - - msg"
        event = _parse_syslog(data, "127.0.0.1", "udp")
        assert event.metadata["seerflow_severity"] == 2  # syslog 5 -> notice -> 2


class TestSyslogReceiverUDP:
    async def test_isinstance_receiver(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test-syslog", udp_port=0, tcp_enabled=False)
        assert isinstance(receiver, Receiver)

    async def test_start_stop_lifecycle(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_port=0, tcp_enabled=False)
        await receiver.start()
        assert receiver.is_healthy()
        await receiver.stop()
        assert not receiver.is_healthy()

    async def test_udp_receive_message(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_port=0, tcp_enabled=False)
        await receiver.start()
        try:
            port = receiver.udp_port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(
                b"<165>1 2026-03-20T04:00:00Z host app - - - test msg",
                ("127.0.0.1", port),
            )
            sock.close()
            await asyncio.sleep(0.1)
            assert mgr.queue_depth == 1
            event = await mgr.get_event()
            assert event.source_type == "syslog"
            assert event.source_id == "test"
        finally:
            await receiver.stop()

    async def test_udp_metadata(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_port=0, tcp_enabled=False)
        await receiver.start()
        try:
            port = receiver.udp_port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(b"<34>Mar 20 04:00:00 host sshd: test", ("127.0.0.1", port))
            sock.close()
            await asyncio.sleep(0.1)
            event = await mgr.get_event()
            assert "remote_addr" in event.metadata
            assert event.metadata["protocol"] == "udp"
        finally:
            await receiver.stop()

    async def test_udp_source_type(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(
            mgr, source_id="syslog-main", udp_port=0, tcp_enabled=False
        )
        await receiver.start()
        try:
            port = receiver.udp_port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(b"<165>test", ("127.0.0.1", port))
            sock.close()
            await asyncio.sleep(0.1)
            event = await mgr.get_event()
            assert event.source_type == "syslog"
            assert event.source_id == "syslog-main"
        finally:
            await receiver.stop()


class TestSyslogReceiverTCP:
    async def test_tcp_receive_message(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_enabled=False, tcp_port=0)
        await receiver.start()
        try:
            port = receiver.tcp_port
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"<165>1 2026-03-20T04:00:00Z host app - - - tcp msg\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.1)
            assert mgr.queue_depth >= 1
            event = await mgr.get_event()
            assert event.metadata["protocol"] == "tcp"
        finally:
            await receiver.stop()

    async def test_tcp_multiple_lines(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_enabled=False, tcp_port=0)
        await receiver.start()
        try:
            port = receiver.tcp_port
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"<165>line1\n<165>line2\n<165>line3\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.2)
            assert mgr.queue_depth >= 3
        finally:
            await receiver.stop()

    async def test_tcp_client_disconnect(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_enabled=False, tcp_port=0)
        await receiver.start()
        try:
            port = receiver.tcp_port
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.1)
        finally:
            await receiver.stop()

    async def test_tcp_metadata(self) -> None:
        mgr = ReceiverManager()
        receiver = SyslogReceiver(mgr, source_id="test", udp_enabled=False, tcp_port=0)
        await receiver.start()
        try:
            port = receiver.tcp_port
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"<34>test msg\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.1)
            event = await mgr.get_event()
            assert "remote_addr" in event.metadata
            assert event.metadata["protocol"] == "tcp"
        finally:
            await receiver.stop()
