"""Tests for the static aiohttp resolver and feed-map builder."""

from __future__ import annotations

import socket

import pytest

from seerflow._config_validation import ConfigError
from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.threat_intel.dns import StaticResolver, build_static_resolver_map


@pytest.mark.asyncio
async def test_static_resolver_returns_pinned_ip_for_known_host() -> None:
    resolver = StaticResolver({"taxii.example": "1.1.1.1"})
    results = await resolver.resolve("taxii.example", port=443)
    assert len(results) == 1
    assert results[0]["host"] == "1.1.1.1"
    assert results[0]["port"] == 443
    assert results[0]["family"] == socket.AF_INET
    await resolver.close()


@pytest.mark.asyncio
async def test_static_resolver_raises_oserror_for_unknown_host() -> None:
    resolver = StaticResolver({"taxii.example": "1.1.1.1"})
    with pytest.raises(OSError, match="static resolver: unknown host"):
        await resolver.resolve("evil.example", port=443)


def test_build_static_resolver_map_skips_disabled_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "1.1.1.1")
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            TAXIIFeedConfig(
                id="enabled",
                url="https://a.example/x",
                collection_id="c",
                enabled=True,
            ),
            TAXIIFeedConfig(
                id="disabled",
                url="https://b.example/x",
                collection_id="c",
                enabled=False,
            ),
        ),
    )
    mapping = build_static_resolver_map(cfg)
    assert "a.example" in mapping
    assert "b.example" not in mapping


def test_build_static_resolver_map_skips_allow_private_addresses_feeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "1.1.1.1")
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            TAXIIFeedConfig(id="public", url="https://a.example/x", collection_id="c"),
            TAXIIFeedConfig(
                id="private",
                url="https://internal.example/x",
                collection_id="c",
                allow_private_addresses=True,
            ),
        ),
    )
    mapping = build_static_resolver_map(cfg)
    assert mapping == {"a.example": "1.1.1.1"}


def test_build_static_resolver_map_pins_literal_ip_unchanged() -> None:
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            TAXIIFeedConfig(id="literal", url="https://1.1.1.1/x", collection_id="c"),
        ),
    )
    mapping = build_static_resolver_map(cfg)
    assert mapping == {"1.1.1.1": "1.1.1.1"}


def test_build_static_resolver_map_propagates_private_ip_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "169.254.169.254")
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            TAXIIFeedConfig(id="rebind", url="https://imds.example/x", collection_id="c"),
        ),
    )
    with pytest.raises(ConfigError, match="private/reserved"):
        build_static_resolver_map(cfg)


def test_build_static_resolver_map_skips_url_without_hostname() -> None:
    """Defensive branch: parsed.hostname None for malformed URL."""
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            # urlparse('https:///x').hostname is None — feed should be skipped
            # without crashing the resolver-map builder.
            TAXIIFeedConfig(id="hostless", url="https:///x", collection_id="c"),
        ),
    )
    mapping = build_static_resolver_map(cfg)
    assert mapping == {}
