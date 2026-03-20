"""Syslog UDP/TCP receiver — RFC 5424 + 3164."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from seerflow.receivers.manager import ReceiverManager

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
