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
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _bypass_dns_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-227: ``aioresponses`` mocks at the aiohttp request layer; the new
    startup DNS guard runs at socket level and is not intercepted. Tests
    use the ``*.example`` reserved domain — substitute a sentinel public
    IP so the static-resolver map builds without hitting the real DNS root.
    """
    monkeypatch.setattr(
        "seerflow.threat_intel.dns._resolve_feed_with_private_ip_guard",
        lambda _feed_id, _hostname: "1.1.1.1",
    )


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


@pytest.mark.asyncio
async def test_load_config_yaml_wires_threat_intel_block(tmp_path) -> None:
    """Regression for the production path: ``load_config()`` must call the
    threat_intel builder and validator, otherwise an opt-in YAML block is
    silently ignored at runtime.
    """
    from seerflow.config import load_config

    cfg_path = tmp_path / "seerflow.yaml"
    cfg_path.write_text(
        """
threat_intel:
  enabled: true
  default_poll_interval_s: 1800
  feeds:
    - id: example
      url: https://taxii.example.invalid/taxii2/api1/
      collection_id: c1
      poll_interval_s: 600
      allow_private_addresses: true
""".strip()
    )

    cfg = load_config(str(cfg_path))

    assert cfg.threat_intel.enabled is True
    assert cfg.threat_intel.default_poll_interval_s == 1800
    assert len(cfg.threat_intel.feeds) == 1
    feed = cfg.threat_intel.feeds[0]
    assert feed.id == "example"
    assert feed.collection_id == "c1"
    assert feed.poll_interval_s == 600


@pytest.mark.asyncio
async def test_load_config_yaml_runs_validator_for_insecure_url(tmp_path) -> None:
    """Validator must reject ``http://`` URLs without an explicit opt-in,
    proving ``validate_seerflow_config`` is wired into ``load_config``.
    """
    from seerflow.config import ConfigError, load_config

    cfg_path = tmp_path / "seerflow.yaml"
    cfg_path.write_text(
        """
threat_intel:
  enabled: true
  feeds:
    - id: bad
      url: http://insecure.example/taxii2/api1/
      collection_id: c1
""".strip()
    )

    with pytest.raises(ConfigError, match="https"):
        load_config(str(cfg_path))
