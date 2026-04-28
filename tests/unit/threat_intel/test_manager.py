"""Tests for TAXIIFeedManager (S-067 Task 11)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.threat_intel.manager import TAXIIFeedManager


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
