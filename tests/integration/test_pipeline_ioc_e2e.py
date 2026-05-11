"""End-to-end pipeline test for IoC alert + enrichment (S-069)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import msgspec
import pytest

from seerflow.config import (
    IoCMatcherConfig,
    SeerflowConfig,
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.pipeline.handler import make_handler
from seerflow.receivers.base import RawEvent
from seerflow.storage.sqlite import SqliteBackend
from seerflow.threat_intel.enricher import _IoCEnrichmentCounters
from seerflow.threat_intel.matcher import IoCMatcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ioc_match_produces_alert_and_enriches_event(tmp_path: Path) -> None:
    feed_id = "test-feed"
    storage_cfg = StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "ioc.db"))
    storage = await SqliteBackend.connect(storage_cfg)
    try:
        snapshot = IndicatorSnapshot(
            feed_id=feed_id,
            fetched_at_ns=time.time_ns(),
            cursor=None,
            indicators=(
                Indicator(
                    value="1.2.3.4",
                    type="ipv4",
                    source_feed=feed_id,
                    confidence=75,
                    kill_chain_phases=("command-and-control",),
                    valid_from_ns=0,
                    valid_until_ns=None,
                ),
            ),
        )
        await storage.save_state(
            f"taxii:snapshot:{feed_id}",
            msgspec.msgpack.encode(snapshot),
        )

        ti_cfg = ThreatIntelConfig(
            enabled=True,
            matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=10),
            feeds=(TAXIIFeedConfig(id=feed_id, url="https://x", collection_id="c"),),
        )
        matcher = IoCMatcher(config=ti_cfg, model_store=storage)
        await matcher.start()

        counters = _IoCEnrichmentCounters()
        config = SeerflowConfig()
        ensemble = DetectionEnsemble(config.detection)
        handler = make_handler(
            ensemble,
            storage,
            ioc_matcher=matcher,
            ioc_enrichment_counters=counters,
            alerting_config=config.alerting,
        )

        raw = RawEvent(
            data=b"probe from 1.2.3.4",
            source_type="syslog",
            source_id="syslog-test",
            received_ns=time.time_ns(),
            metadata={},
        )
        await handler(raw)
        await matcher.stop()
        await storage.flush()

        alerts = await storage.query_alerts(AlertQuery(limit=10))
        ioc_alerts = [a for a in alerts.items if a.alert_type == "ioc"]
        assert len(ioc_alerts) == 1
        a = ioc_alerts[0]
        assert a.rule_name == f"ti:{feed_id}"
        assert a.severity_id == 4
        assert a.mitre_tactics == ("TA0011",)
        events = await storage.query_events(EventQuery(limit=10))
        # First event should carry the ioc_matches enrichment.
        enriched = next(
            (e for e in events.items if e.attributes.get("ioc_matches")),
            None,
        )
        assert enriched is not None
        assert enriched.attributes["ioc_matches"][0]["value"] == "1.2.3.4"  # type: ignore[index]
        assert counters.alerts_emitted_total == 1

        # Idempotency: second feed of the same event hits dedup.
        await handler(raw)
        await storage.flush()
        alerts2 = await storage.query_alerts(AlertQuery(limit=10))
        ioc_alerts2 = [a for a in alerts2.items if a.alert_type == "ioc"]
        assert len(ioc_alerts2) == 1
        assert counters.alerts_deduped_total == 1
    finally:
        await storage.close()
