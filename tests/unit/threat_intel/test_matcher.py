"""Unit tests for IoCMatcher (S-068)."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.config import IoCMatcherConfig, TAXIIFeedConfig, ThreatIntelConfig
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.threat_intel.matcher import (
    IoCMatcher,
    IoCMatcherMetrics,
)


@pytest.fixture
def stub_store() -> object:
    class _Store:
        async def save_state(self, key: str, data: bytes) -> None:
            return None

        async def load_state(self, key: str) -> bytes | None:
            return None

        async def delete_state(self, key: str) -> None:
            return None

    return _Store()


def test_initial_metrics_are_zero(stub_store: object) -> None:
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))
    matcher = IoCMatcher(config=cfg, model_store=stub_store)  # type: ignore[arg-type]
    snap = matcher.metrics_snapshot()
    assert isinstance(snap, IoCMatcherMetrics)
    assert snap.rebuild_count == 0
    assert snap.checks_total == 0
    assert snap.bloom_hits_total == 0
    assert snap.confirmed_matches_total == 0
    assert snap.false_positives_total == 0
    assert snap.last_rebuild_at_ns is None
    assert snap.indicators_loaded == {}


class _MemStore:
    """Async in-memory ModelStore for tests."""

    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}

    async def save_state(self, key: str, data: bytes) -> None:
        self._kv[key] = bytes(data)

    async def load_state(self, key: str) -> bytes | None:
        return self._kv.get(key)

    async def delete_state(self, key: str) -> None:
        self._kv.pop(key, None)


def _seed_snapshot(store: _MemStore, feed_id: str, *indicators: Indicator) -> None:
    snap = IndicatorSnapshot(
        feed_id=feed_id,
        fetched_at_ns=1,
        indicators=tuple(indicators),
        cursor=None,
    )
    import asyncio

    asyncio.get_event_loop().run_until_complete(
        store.save_state(f"taxii:snapshot:{feed_id}", msgspec.msgpack.encode(snap))
    )


def _ipv4(value: str, *, source: str = "f1", confidence: int = 80) -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed=source,
        confidence=confidence,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


@pytest.mark.asyncio
async def test_refresh_loads_from_single_feed_snapshot() -> None:
    store = _MemStore()
    feed = TAXIIFeedConfig(id="f1", url="https://x", collection_id="c")
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(feed,),
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    snap_metrics = matcher.metrics_snapshot()
    assert snap_metrics.rebuild_count == 1
    assert snap_metrics.indicators_loaded == {"ipv4": 1}
    assert snap_metrics.bit_array_bytes > 0
    assert snap_metrics.last_rebuild_at_ns is not None


@pytest.mark.asyncio
async def test_refresh_unions_multiple_feeds() -> None:
    store = _MemStore()
    feeds = (
        TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),
        TAXIIFeedConfig(id="f2", url="https://y", collection_id="d"),
    )
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    for fid, val in (("f1", "1.2.3.4"), ("f2", "5.6.7.8")):
        s = IndicatorSnapshot(
            feed_id=fid,
            fetched_at_ns=1,
            indicators=(_ipv4(val, source=fid),),
            cursor=None,
        )
        await store.save_state(f"taxii:snapshot:{fid}", msgspec.msgpack.encode(s))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 2}


@pytest.mark.asyncio
async def test_refresh_filters_by_confidence_floor() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, confidence_floor=50),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            _ipv4("1.2.3.4", confidence=80),
            _ipv4("9.9.9.9", confidence=10),  # below floor
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 1}


@pytest.mark.asyncio
async def test_refresh_skips_disabled_types() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, enabled_types=("domain",)),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),  # ipv4 disabled
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {}
