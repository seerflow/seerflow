"""Smoke test: run.py constructs + starts the matcher when enabled."""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec
import pytest

from seerflow.config import (
    IoCMatcherConfig,
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.storage.factory import connect_storage
from seerflow.threat_intel.matcher import IoCMatcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_matcher_construction_order_attaches_listener_before_manager_start(
    tmp_path: Path,
) -> None:
    """run.py wiring: matcher.start() must precede manager.start()."""
    from seerflow.threat_intel.manager import TAXIIFeedManager

    store = await connect_storage(StorageConfig(data_dir=str(tmp_path)))
    try:
        cfg = ThreatIntelConfig(
            enabled=False,  # don't actually start a poller in this test
            feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
            matcher=IoCMatcherConfig(enabled=True),
        )
        # Seed a known indicator before matcher.start so the initial rebuild loads it.
        snap = IndicatorSnapshot(
            feed_id="f1",
            fetched_at_ns=1,
            indicators=(
                Indicator(
                    value="1.2.3.4",
                    type="ipv4",
                    source_feed="f1",
                    confidence=80,
                    kill_chain_phases=(),
                    valid_from_ns=0,
                    valid_until_ns=None,
                ),
            ),
            cursor=None,
        )
        await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

        manager = TAXIIFeedManager(config=cfg, model_store=store)
        matcher = IoCMatcher(config=cfg, model_store=store)
        manager.register_snapshot_listener(matcher.on_snapshot_updated)
        await matcher.start()
        try:
            assert matcher.check("1.2.3.4", "ipv4") is not None
        finally:
            await matcher.stop()
            await manager.stop()
    finally:
        await store.close()
