"""Static aiohttp resolver pinned to startup-resolved IPv4 addresses.

Mitigates DNS rebinding (S-227 AC1, Reviewer 5 MEDIUM-1 on PR #218).
``aiohttp.ClientSession`` re-resolves DNS independently per request via
``ThreadedResolver.resolve``. An attacker controlling a feed's DNS zone
can return a public IP at startup and then a private/loopback / cloud
IMDS address at runtime. This module captures each feed hostname's IP
once at startup (reusing the ``_is_private_ip`` SSRF guard from
``_config_validation``) and replaces ``aiohttp``'s default resolver so
runtime requests cannot drift from the validated answer.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import ResolveResult

from seerflow._config_validation import _resolve_feed_with_private_ip_guard

if TYPE_CHECKING:
    from seerflow.config import ThreatIntelConfig


class StaticResolver(AbstractResolver):
    """Returns the pinned IPv4 for known hosts; raises ``OSError`` for unknown hosts."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = mapping

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        ip = self._map.get(host)
        if ip is None:
            raise OSError(f"static resolver: unknown host {host!r}")
        return [
            ResolveResult(
                hostname=host,
                host=ip,
                port=port,
                family=family,
                proto=0,
                flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
        ]

    async def close(self) -> None:
        return None


def build_static_resolver_map(config: ThreatIntelConfig) -> dict[str, str]:
    """Resolve each enabled feed's hostname once and return ``{host: ip}``.

    Skips disabled feeds and feeds with ``allow_private_addresses=True`` —
    those run through aiohttp's default resolver. Re-uses
    ``_resolve_feed_with_private_ip_guard`` so the SSRF rejection logic
    stays in one place.
    """
    out: dict[str, str] = {}
    for feed in config.feeds:
        if not feed.enabled or feed.allow_private_addresses:
            continue
        parsed = urlparse(feed.url)
        if not parsed.hostname:
            continue
        out[parsed.hostname] = _resolve_feed_with_private_ip_guard(feed.id, parsed.hostname)
    return out
