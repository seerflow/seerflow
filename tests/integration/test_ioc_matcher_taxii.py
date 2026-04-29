"""TAXIIFeedConsumer + IoCMatcher integration: poll → persist → matcher rebuild."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.config import (
    IoCMatcherConfig,
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.storage.factory import connect_storage
from seerflow.threat_intel.matcher import IoCMatcher


@pytest.mark.asyncio
async def test_listener_pushes_match_into_matcher(tmp_path: Path) -> None:
    """Direct listener invocation drives matcher refresh after a manual persist."""
    import msgspec

    store = await connect_storage(StorageConfig(data_dir=str(tmp_path)))
    try:
        cfg = ThreatIntelConfig(
            enabled=True,
            feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
            matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=5),
        )
        matcher = IoCMatcher(config=cfg, model_store=store)
        await matcher.start()
        try:
            assert matcher.check("1.2.3.4", "ipv4") is None  # cold start

            # Simulate the consumer persisting a snapshot then firing the listener.
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
            matcher.on_snapshot_updated("f1")
            # Wait through debounce + rebuild.
            await asyncio.sleep(0.1)

            assert matcher.check("1.2.3.4", "ipv4") is not None
            assert matcher.check("9.9.9.9", "ipv4") is None
        finally:
            await matcher.stop()
    finally:
        await store.close()
