"""Tests for TAXIIFeedConsumer (S-067 Task 10)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import msgspec
import pytest

from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.threat_intel.circuit import AuthCircuitBreaker
from seerflow.threat_intel.consumer import TAXIIFeedConsumer
from seerflow.threat_intel.metrics import TAXIIMetricsRegistry


@pytest.fixture
def feed_cfg() -> TAXIIFeedConfig:
    return TAXIIFeedConfig(
        id="otx",
        url="https://taxii.example/taxii2/",
        collection_id="abc",
        poll_interval_s=60,
    )


@pytest.fixture
def defaults() -> ThreatIntelConfig:
    return ThreatIntelConfig(
        enabled=True,
        max_indicators_per_feed=100,
        expired_grace_days=0,
        startup_jitter_s=0,
    )


def _make_indicator(value: str = "1.2.3.4") -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed="otx",
        confidence=0,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


@pytest.mark.asyncio
async def test_poll_once_persists_snapshot_and_advances_cursor(
    feed_cfg: TAXIIFeedConfig, defaults: ThreatIntelConfig
) -> None:
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        yield {"type": "indicator", "id": "i1", "pattern": "[]"}, "2026-01-01T00:00:00Z"

    fake_client.get_objects = _gen

    parser = MagicMock()
    parser.parse = MagicMock(return_value=(_make_indicator(),))

    metrics = TAXIIMetricsRegistry()
    breaker = AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0)

    consumer = TAXIIFeedConsumer(
        feed_config=feed_cfg,
        defaults=defaults,
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 1_700_000_000_000_000_000,
    )
    snap = await consumer.poll_once()
    assert isinstance(snap, IndicatorSnapshot)
    assert len(snap.indicators) == 1
    assert snap.cursor == "2026-01-01T00:00:00Z"

    # snapshot persisted
    save_calls = model_store.save_state.await_args_list
    saved_keys = {c.args[0] for c in save_calls}
    assert "taxii:snapshot:otx" in saved_keys
    assert "taxii:cursor:otx" in saved_keys

    # roundtrip the snapshot bytes
    snap_bytes = next(c.args[1] for c in save_calls if c.args[0] == "taxii:snapshot:otx")
    decoded = msgspec.msgpack.decode(snap_bytes, type=IndicatorSnapshot)
    assert decoded.feed_id == "otx"


@pytest.mark.asyncio
async def test_poll_once_truncates_at_cap(
    feed_cfg: TAXIIFeedConfig, defaults: ThreatIntelConfig
) -> None:
    capped = ThreatIntelConfig(enabled=True, max_indicators_per_feed=2)
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        for i in range(5):
            yield {"type": "indicator", "id": f"i{i}", "pattern": "[]"}, "2026-04-01T00:00:00Z"

    fake_client.get_objects = _gen

    parser = MagicMock()
    parser.parse = MagicMock(return_value=(_make_indicator(),))
    metrics = TAXIIMetricsRegistry()
    breaker = AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0)

    consumer = TAXIIFeedConsumer(
        feed_config=feed_cfg,
        defaults=capped,
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 0,
    )
    snap = await consumer.poll_once()
    assert len(snap.indicators) == 2
    snap_metrics = metrics.snapshot("otx")
    assert snap_metrics.indicators_truncated_total == 3


@pytest.mark.asyncio
async def test_run_forever_stops_on_event(
    feed_cfg: TAXIIFeedConfig, defaults: ThreatIntelConfig
) -> None:
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        if False:  # empty generator
            yield  # pragma: no cover

    fake_client.get_objects = _gen
    parser = MagicMock()
    parser.parse = MagicMock(return_value=())
    metrics = TAXIIMetricsRegistry()
    breaker = AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0)

    short = ThreatIntelConfig(enabled=True, default_poll_interval_s=0, startup_jitter_s=0)
    cfg = TAXIIFeedConfig(
        id="otx",
        url="https://x/",
        collection_id="c",
        poll_interval_s=0,
    )
    consumer = TAXIIFeedConsumer(
        feed_config=cfg,
        defaults=short,
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 0,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(consumer.run_forever(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
