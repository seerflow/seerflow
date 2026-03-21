"""Regex-based entity extraction from log messages."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from seerflow.parsing._constants import MAX_ENTITIES_PER_TYPE, MAX_MESSAGE_LEN

if TYPE_CHECKING:
    from collections.abc import Callable

_ALL_ENTITY_TYPES = frozenset({"ip", "user", "host", "file", "domain"})

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
    r"(?:user=|for user )([a-zA-Z0-9._@-]{1,64})",
    re.IGNORECASE,
)

_HOST_RE = re.compile(
    r"(?:host(?:name)?[= ])"
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


# NOTE: URL paths (e.g. /api/v1/health) may match as file paths — acceptable
# trade-off for v1; will be refined in a future story.
_FILE_RE = re.compile(r"(?:^|(?<=\s))(/(?:[a-zA-Z0-9._-]+/)*[a-zA-Z0-9._-]+)")

_NON_TLD = frozenset(
    {
        "conf",
        "log",
        "txt",
        "py",
        "sh",
        "yml",
        "yaml",
        "json",
        "xml",
        "gz",
        "bz2",
        "xz",
        "zst",
        "tar",
        "zip",
        "csv",
        "ini",
        "cfg",
        "pid",
        "sock",
        "lock",
        "tmp",
        "bak",
        "old",
    }
)

_DOMAIN_RE = re.compile(
    r"\b([a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?){0,10}"
    r"\.[a-zA-Z]{2,63})\b"
)


def _extract_hosts(message: str) -> list[str]:
    """Extract unique hostnames from a log message."""
    candidates = _HOST_RE.findall(message)
    return list(dict.fromkeys(c for c in candidates if not _IPV4_RE.fullmatch(c)))


def _extract_files(message: str) -> list[str]:
    """Extract unique absolute file paths from a log message."""
    return list(dict.fromkeys(_FILE_RE.findall(message)))


def _extract_domains(message: str) -> list[str]:
    """Extract unique domain names from a log message, excluding IPs."""
    candidates = _DOMAIN_RE.findall(message)
    return list(
        dict.fromkeys(
            c
            for c in candidates
            if not _IPV4_RE.fullmatch(c) and c.rsplit(".", 1)[-1].lower() not in _NON_TLD
        )
    )


# Mapping from entity type name to its extraction function
_EXTRACTORS: dict[str, Callable[[str], list[str]]] = {
    "ip": _extract_ips,
    "user": _extract_users,
    "host": _extract_hosts,
    "file": _extract_files,
    "domain": _extract_domains,
}


class EntityExtractor:
    """Compose regex extractors to pull structured entities from log messages.

    By default all entity types are extracted. Pass ``enabled_types`` to
    restrict to a subset (e.g. ``frozenset({"ip", "user"})``).
    """

    __slots__ = ("_extractors",)

    def __init__(
        self,
        *,
        enabled_types: frozenset[str] | None = None,
    ) -> None:
        types = enabled_types if enabled_types is not None else _ALL_ENTITY_TYPES
        unknown = types - _ALL_ENTITY_TYPES
        if unknown:
            msg = f"Unknown entity types: {unknown!r}. Valid: {_ALL_ENTITY_TYPES!r}"
            raise ValueError(msg)
        self._extractors: dict[str, Callable[[str], list[str]]] = {
            t: _EXTRACTORS[t] for t in types
        }

    def extract(self, message: str) -> dict[str, list[str]]:
        """Extract all enabled entity types from *message*."""
        if len(message) > MAX_MESSAGE_LEN:
            message = message[:MAX_MESSAGE_LEN]
        return {name: fn(message)[:MAX_ENTITIES_PER_TYPE] for name, fn in self._extractors.items()}
