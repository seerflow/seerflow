"""Static aiohttp resolver pinned to startup-resolved IPv4 addresses.

Mitigates DNS rebinding (S-227 AC1, Reviewer 5 MEDIUM-1 on PR #218).
``aiohttp.ClientSession`` re-resolves DNS independently per request via
``ThreadedResolver.resolve``. An attacker controlling a feed's DNS zone
can return a public IP at startup and then a private/loopback / cloud
IMDS address at runtime. This module captures each feed hostname's IP
once at startup (reusing the ``_is_private_ip`` SSRF guard from
``_config_validation``) and replaces ``aiohttp``'s default resolver so
runtime requests cannot drift from the validated answer.

Mixed configurations (public feeds + ``allow_private_addresses`` opt-out
feeds in the same ``ThreatIntelConfig``) keep working: the resolver
delegates unknown hosts to a fallback resolver (``ThreadedResolver`` by
default). Public feeds are pinned; opt-out feeds resolve normally
through aiohttp's default path.
"""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import ThreadedResolver

from seerflow._config_validation import _resolve_feed_with_private_ip_guard

if TYPE_CHECKING:
    from seerflow.config import ThreatIntelConfig


class StaticResolver(AbstractResolver):
    """Pin known hosts to startup IPs; delegate unknown hosts to a fallback.

    Hosts in ``mapping`` resolve to the captured IPv4 with no further DNS
    lookup. Hosts absent from the mapping fall through to the fallback
    resolver (default: ``aiohttp.resolver.ThreadedResolver``) so feeds
    that opted out of the static-pinning guard via
    ``allow_private_addresses=True`` continue to function in mixed
    configurations.
    """

    def __init__(
        self,
        mapping: dict[str, str],
        *,
        fallback: AbstractResolver | None = None,
    ) -> None:
        self._map = dict(mapping)
        self._fallback = fallback if fallback is not None else ThreadedResolver()

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        ip = self._map.get(host)
        if ip is None:
            # Opt-out feed (allow_private_addresses=True) or any host outside
            # the pinned set — defer to the fallback resolver. Operators who
            # mix public and trusted-internal feeds in the same config still
            # get the static pin for the public ones.
            return await self._fallback.resolve(host, port, family)
        # Pinned IPv4 — force AF_INET in the result so the connector cannot
        # interpret the literal as anything else, regardless of what the
        # caller passed (TCPConnector defaults to AF_UNSPEC).
        return [
            ResolveResult(
                hostname=host,
                host=ip,
                port=port,
                family=socket.AF_INET,
                proto=0,
                flags=socket.AI_NUMERICHOST | socket.AI_NUMERICSERV,
            )
        ]

    async def close(self) -> None:
        await self._fallback.close()


def build_static_resolver_map(config: ThreatIntelConfig) -> dict[str, str]:
    """Resolve each enabled feed's hostname once and return ``{host: ip}``.

    Skips disabled feeds and feeds with ``allow_private_addresses=True`` —
    those run through the fallback resolver at request time. Re-uses
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
