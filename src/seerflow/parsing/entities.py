"""Regex-based entity extraction from log messages."""

from __future__ import annotations

import re

# IPv4 — valid octets 0-255 with word boundaries
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)

# IPv6 — simplified pattern covering common forms
_IPV6_RE = re.compile(
    r"(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}"  # full
    r"|(?:[0-9a-fA-F]{1,4}:){1,7}:"  # trailing ::
    r"|(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"  # :: in middle
    r"|::(?:[0-9a-fA-F]{1,4}:){0,5}[0-9a-fA-F]{1,4}"  # leading ::
    r"|::1"  # loopback
    r"|::)"  # all zeros
)


_USER_RE = re.compile(
    r"(?:user[= ]|for user |by )([a-zA-Z0-9._-]+)",
    re.IGNORECASE,
)

_HOST_RE = re.compile(
    r"(?:host(?:name)?[= ]|on )"
    r"([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*)",
    re.IGNORECASE,
)


def _extract_ips(message: str) -> list[str]:
    """Extract unique IPv4 and IPv6 addresses from a log message."""
    ipv4 = _IPV4_RE.findall(message)
    ipv6 = _IPV6_RE.findall(message)
    return list(dict.fromkeys(ipv4 + ipv6))  # dedup preserving order


def _extract_users(message: str) -> list[str]:
    """Extract unique usernames from a log message."""
    return list(dict.fromkeys(_USER_RE.findall(message)))


def _extract_hosts(message: str) -> list[str]:
    """Extract unique hostnames from a log message."""
    return list(dict.fromkeys(_HOST_RE.findall(message)))
