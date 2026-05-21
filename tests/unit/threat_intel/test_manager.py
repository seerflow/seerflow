"""Tests for TAXIIFeedManager (S-067 Task 11)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.threat_intel.manager import TAXIIFeedManager

if TYPE_CHECKING:
    from pathlib import Path


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


async def test_manager_disabled_is_noop() -> None:
    mgr = TAXIIFeedManager(config=ThreatIntelConfig(enabled=False), model_store=MagicMock())
    failed = await mgr.start()
    assert failed == []
    assert mgr.feed_ids() == ()
    await mgr.stop()


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


async def test_register_snapshot_listener_fires_on_consumer_persist(monkeypatch) -> None:
    """Manager fires registered listeners after a successful consumer persist."""
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
    )

    class _Store:
        async def save_state(self, key: str, data: bytes) -> None:
            return None

        async def load_state(self, key: str) -> bytes | None:
            return None

        async def delete_state(self, key: str) -> None:
            return None

    captured: list[str] = []
    manager = TAXIIFeedManager(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    manager.register_snapshot_listener(captured.append)
    manager._fire_snapshot_listeners("f1")  # type: ignore[attr-defined]
    assert captured == ["f1"]


async def test_listener_exception_does_not_break_others(monkeypatch) -> None:
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
    )

    class _Store:
        async def save_state(self, key: str, data: bytes) -> None:
            return None

        async def load_state(self, key: str) -> bytes | None:
            return None

        async def delete_state(self, key: str) -> None:
            return None

    def boom(_fid: str) -> None:
        raise RuntimeError("listener exploded")

    captured: list[str] = []
    manager = TAXIIFeedManager(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    manager.register_snapshot_listener(boom)
    manager.register_snapshot_listener(captured.append)
    manager._fire_snapshot_listeners("f1")  # type: ignore[attr-defined]
    assert captured == ["f1"]
