"""Tests for SyslogReceiver — parsing, severity, UDP, TCP."""

from __future__ import annotations

import pytest

from seerflow.receivers.syslog import (
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
