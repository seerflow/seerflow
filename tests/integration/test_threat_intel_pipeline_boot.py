"""Pipeline boots cleanly with threat_intel disabled and enabled.

The plan-spec uses ``build_stores`` / ``stores.model_store`` / ``stores.close()``
shapes. The real factory in this repo is ``connect_storage(storage_cfg)``
returning a ``SqliteBackend`` whose own surface satisfies the
``ModelStore`` Protocol (``save_state`` / ``load_state``) and exposes
``close()``. The test contract is preserved: build a real SQLite-backed
model store, run two mocked feeds end-to-end, decode the persisted
snapshot, verify the indicator value round-tripped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import msgspec
import pytest
from aioresponses import aioresponses

from seerflow.config import (
    SeerflowConfig,
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.models.indicator import IndicatorSnapshot
from seerflow.storage import connect_storage
from seerflow.threat_intel.manager import TAXIIFeedManager


@pytest.mark.asyncio
async def test_disabled_threat_intel_does_not_construct_session(tmp_path: Path) -> None:
    cfg = SeerflowConfig(
        storage=StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "s.db")),
        threat_intel=ThreatIntelConfig(enabled=False),
    )
    storage = await connect_storage(cfg.storage)
    try:
        mgr = TAXIIFeedManager(config=cfg.threat_intel, model_store=storage)
        failed = await mgr.start()
        assert failed == []
        assert mgr.feed_ids() == ()
        await mgr.stop()
    finally:
        await storage.close()


@pytest.mark.asyncio
async def test_two_feeds_persist_snapshots(tmp_path: Path) -> None:
    feeds = (
        TAXIIFeedConfig(
            id="a",
            url="https://taxii-a.example/taxii2/",
            collection_id="ca",
            poll_interval_s=60,
        ),
        TAXIIFeedConfig(
            id="b",
            url="https://taxii-b.example/taxii2/",
            collection_id="cb",
            poll_interval_s=60,
        ),
    )
    cfg = SeerflowConfig(
        storage=StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "s.db")),
        threat_intel=ThreatIntelConfig(
            enabled=True,
            feeds=feeds,
            startup_jitter_s=0,
        ),
    )
    storage = await connect_storage(cfg.storage)

    try:
        with aioresponses() as m:
            ipv4 = {
                "type": "indicator",
                "spec_version": "2.1",
                "id": "indicator--00000000-0000-0000-0000-000000000001",
                "created": "2026-04-01T00:00:00Z",
                "modified": "2026-04-01T00:00:00Z",
                "valid_from": "2026-04-01T00:00:00Z",
                "pattern": "[ipv4-addr:value = '198.51.100.1']",
                "pattern_type": "stix",
            }
            m.get(
                "https://taxii-a.example/taxii2/collections/ca/objects/",
                status=200,
                payload={"objects": [ipv4], "more": False},
                headers={"X-TAXII-Date-Added-Last": "2026-04-01T00:00:00.000Z"},
            )
            m.get(
                "https://taxii-b.example/taxii2/collections/cb/objects/",
                status=200,
                payload={"objects": [ipv4], "more": False},
                headers={"X-TAXII-Date-Added-Last": "2026-04-01T00:00:00.000Z"},
            )

            mgr = TAXIIFeedManager(config=cfg.threat_intel, model_store=storage)
            await mgr.start()
            # let both consumers finish their first poll
            await asyncio.sleep(0.5)
            await mgr.stop()

        for feed_id in ("a", "b"):
            raw = await storage.load_state(f"taxii:snapshot:{feed_id}")
            assert raw is not None
            snap = msgspec.msgpack.decode(raw, type=IndicatorSnapshot)
            assert snap.feed_id == feed_id
            assert any(ind.value == "198.51.100.1" for ind in snap.indicators)
    finally:
        await storage.close()
