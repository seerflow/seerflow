"""Tests for TAXIIFeedManager (S-067 Task 11)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.threat_intel.manager import TAXIIFeedManager


@pytest.fixture(autouse=True)
def _bypass_dns_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-227: ``TAXIIFeedManager.start()`` resolves each feed hostname at
    socket level to populate the static aiohttp resolver. Tests use stub
    hostnames like ``a`` / ``x`` that don't resolve; substitute a sentinel
    public IP so the resolver-map builder succeeds without hitting real
    DNS.
    """
    monkeypatch.setattr(
        "seerflow.threat_intel.dns._resolve_feed_with_private_ip_guard",
        lambda _feed_id, _hostname: "1.1.1.1",
    )


@pytest.mark.asyncio
async def test_manager_starts_one_task_per_enabled_feed() -> None:
    cfg = ThreatIntelConfig(
        enabled=True,
        startup_jitter_s=0,
        default_poll_interval_s=60,
        feeds=(
            TAXIIFeedConfig(id="a", url="https://a/", collection_id="c"),
            TAXIIFeedConfig(id="b", url="https://b/", collection_id="c", enabled=False),
        ),
    )
    store = MagicMock()
    store.save_state = AsyncMock()
    store.load_state = AsyncMock(return_value=None)
    mgr = TAXIIFeedManager(config=cfg, model_store=store)
    failed = await mgr.start()
    try:
        assert failed == []
        assert mgr.feed_ids() == ("a",)
    finally:
        await mgr.stop()


@pytest.mark.asyncio
async def test_manager_disabled_is_noop() -> None:
    mgr = TAXIIFeedManager(config=ThreatIntelConfig(enabled=False), model_store=MagicMock())
    failed = await mgr.start()
    assert failed == []
    assert mgr.feed_ids() == ()
    await mgr.stop()


@pytest.mark.asyncio
async def test_manager_stop_cancels_in_flight_tasks() -> None:
    cfg = ThreatIntelConfig(
        enabled=True,
        startup_jitter_s=0,
        default_poll_interval_s=10,
        feeds=(TAXIIFeedConfig(id="x", url="https://x/", collection_id="c"),),
    )
    store = MagicMock()
    store.save_state = AsyncMock()
    store.load_state = AsyncMock(return_value=None)
    mgr = TAXIIFeedManager(config=cfg, model_store=store)
    await mgr.start()
    await asyncio.sleep(0.01)
    await asyncio.wait_for(mgr.stop(), timeout=5.0)


# --- S-227 AC1: TAXIIFeedManager.start() wires StaticResolver -------------


@pytest.mark.asyncio
async def test_start_installs_static_resolver_for_enabled_public_feeds(
    tmp_path: Path,
) -> None:
    import aiohttp

    from seerflow.config import StorageConfig
    from seerflow.storage import connect_storage
    from seerflow.threat_intel.dns import StaticResolver

    storage = await connect_storage(
        StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "s.db"))
    )
    try:
        cfg = ThreatIntelConfig(
            enabled=True,
            feeds=(TAXIIFeedConfig(id="a", url="https://a.example/x", collection_id="c"),),
            startup_jitter_s=0,
        )
        mgr = TAXIIFeedManager(config=cfg, model_store=storage)
        try:
            await mgr.start()
            session = mgr._session
            assert session is not None
            connector = session.connector
            assert isinstance(connector, aiohttp.TCPConnector)
            assert isinstance(connector._resolver, StaticResolver)
        finally:
            await mgr.stop()
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_start_uses_default_session_when_all_feeds_allow_private(
    tmp_path: Path,
) -> None:
    from seerflow.config import StorageConfig
    from seerflow.storage import connect_storage
    from seerflow.threat_intel.dns import StaticResolver

    storage = await connect_storage(
        StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "s.db"))
    )
    try:
        cfg = ThreatIntelConfig(
            enabled=True,
            feeds=(
                TAXIIFeedConfig(
                    id="p",
                    url="https://internal.example/x",
                    collection_id="c",
                    allow_private_addresses=True,
                ),
            ),
            startup_jitter_s=0,
        )
        mgr = TAXIIFeedManager(config=cfg, model_store=storage)
        try:
            await mgr.start()
            assert mgr._session is not None
            connector = mgr._session.connector
            # No StaticResolver injected — default resolver path.
            assert not isinstance(connector._resolver, StaticResolver)
        finally:
            await mgr.stop()
    finally:
        await storage.close()
