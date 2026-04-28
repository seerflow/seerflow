"""Branch coverage tests for TAXIIFeedConsumer (S-067).

Targets the missing branches identified in coverage:
- Circuit-open early-return path (``_breaker.allow()`` returns False).
- ``_filter_confidence`` non-zero floor branch.
- ``_classify_failure`` 401/403/other branches.
- ``run_forever`` jitter and post-poll wait branches that observe ``stop``.
- ``GetWithRetryError`` raised mid-poll -> empty snapshot return path.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.threat_intel.circuit import AuthCircuitBreaker
from seerflow.threat_intel.consumer import TAXIIFeedConsumer
from seerflow.threat_intel.metrics import TAXIIMetricsRegistry
from seerflow.utils.http import GetWithRetryError


def _ind(value: str = "1.2.3.4", *, confidence: int = 0) -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed="otx",
        confidence=confidence,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


def _feed_cfg(*, confidence_floor: int = 0) -> TAXIIFeedConfig:
    return TAXIIFeedConfig(
        id="otx",
        url="https://taxii.example/taxii2/",
        collection_id="abc",
        poll_interval_s=60,
        confidence_floor=confidence_floor,
    )


def _defaults(**kw: Any) -> ThreatIntelConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "max_indicators_per_feed": 100,
        "expired_grace_days": 0,
        "startup_jitter_s": 0,
    }
    base.update(kw)
    return ThreatIntelConfig(**base)


@pytest.mark.asyncio
async def test_poll_once_returns_empty_when_circuit_is_open() -> None:
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()
    parser = MagicMock()
    parser.parse = MagicMock(return_value=())

    metrics = TAXIIMetricsRegistry()
    breaker = MagicMock()
    breaker.allow = MagicMock(return_value=False)

    consumer = TAXIIFeedConsumer(
        feed_config=_feed_cfg(),
        defaults=_defaults(),
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 42,
    )

    snap = await consumer.poll_once()
    assert isinstance(snap, IndicatorSnapshot)
    assert snap.indicators == ()
    assert snap.cursor is None
    assert snap.fetched_at_ns == 42
    # Circuit-open metric flagged on for this feed.
    assert metrics.snapshot("otx").circuit_open is True
    # No save attempts because we short-circuited before the fetch.
    model_store.save_state.assert_not_called()
    model_store.load_state.assert_not_called()


@pytest.mark.asyncio
async def test_filter_confidence_drops_below_floor() -> None:
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        yield {"type": "indicator", "id": "i1", "pattern": "[]"}, "2026-04-01T00:00:00Z"

    fake_client.get_objects = _gen
    parser = MagicMock()
    parser.parse = MagicMock(
        return_value=(_ind("1.1.1.1", confidence=10), _ind("2.2.2.2", confidence=80)),
    )
    metrics = TAXIIMetricsRegistry()
    breaker = AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0)

    consumer = TAXIIFeedConsumer(
        feed_config=_feed_cfg(confidence_floor=50),
        defaults=_defaults(),
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 0,
    )

    snap = await consumer.poll_once()
    assert len(snap.indicators) == 1
    assert snap.indicators[0].value == "2.2.2.2"


def _make_consumer_with_failing_client(
    *,
    error_msg: str,
) -> tuple[TAXIIFeedConsumer, TAXIIMetricsRegistry, AuthCircuitBreaker]:
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        # Yield once so the loop body runs, then raise mid-iteration.
        yield {"type": "indicator", "id": "i1", "pattern": "[]"}, "ts"
        raise GetWithRetryError(error_msg)

    fake_client.get_objects = _gen
    parser = MagicMock()
    parser.parse = MagicMock(return_value=())
    metrics = TAXIIMetricsRegistry()
    breaker = AuthCircuitBreaker(threshold=2, open_seconds=60, now_fn=lambda: 0.0)
    consumer = TAXIIFeedConsumer(
        feed_config=_feed_cfg(),
        defaults=_defaults(),
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=metrics,
        breaker=breaker,
        clock_ns=lambda: 100,
    )
    return consumer, metrics, breaker


@pytest.mark.asyncio
async def test_classify_failure_records_auth_on_401() -> None:
    consumer, metrics, breaker = _make_consumer_with_failing_client(
        error_msg="GET https://x failed: status 401",
    )
    snap = await consumer.poll_once()
    assert snap.indicators == ()
    assert snap.fetched_at_ns == 100
    snap_metrics = metrics.snapshot("otx")
    assert snap_metrics.polls_auth_failed_total == 1
    assert snap_metrics.polls_failed_total == 0
    # Breaker bumped once -- threshold not yet reached.
    assert breaker.is_open() is False


@pytest.mark.asyncio
async def test_classify_failure_records_auth_on_403() -> None:
    consumer, metrics, _ = _make_consumer_with_failing_client(
        error_msg="GET https://x failed: status 403",
    )
    await consumer.poll_once()
    snap_metrics = metrics.snapshot("otx")
    assert snap_metrics.polls_auth_failed_total == 1


@pytest.mark.asyncio
async def test_classify_failure_records_non_auth_on_other_status() -> None:
    consumer, metrics, breaker = _make_consumer_with_failing_client(
        error_msg="GET https://x failed: status 502",
    )
    await consumer.poll_once()
    snap_metrics = metrics.snapshot("otx")
    assert snap_metrics.polls_failed_total == 1
    assert snap_metrics.polls_auth_failed_total == 0
    # Breaker untouched on non-auth failure.
    assert breaker.is_open() is False


@pytest.mark.asyncio
async def test_run_forever_returns_during_jitter_when_stop_already_set() -> None:
    """Cover line 113 — stop fires during the jitter wait_for window."""
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):  # pragma: no cover - never reached
        if False:
            yield  # pragma: no cover

    fake_client.get_objects = _gen
    parser = MagicMock()
    parser.parse = MagicMock(return_value=())

    # Non-zero jitter so wait_for can resolve via stop.set() before timeout.
    consumer = TAXIIFeedConsumer(
        feed_config=_feed_cfg(),
        defaults=_defaults(startup_jitter_s=2, default_poll_interval_s=60),
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=TAXIIMetricsRegistry(),
        breaker=AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0),
        clock_ns=lambda: 0,
    )

    stop = asyncio.Event()
    stop.set()  # already set -> jitter wait_for resolves immediately.
    # Should return without polling.
    await asyncio.wait_for(consumer.run_forever(stop), timeout=1.0)
    parser.parse.assert_not_called()


@pytest.mark.asyncio
async def test_run_forever_returns_during_post_poll_wait_when_stop_set() -> None:
    """Cover line 120 — wait_for(stop, poll_interval) resolves via stop, returns.

    The jitter window is 0 (TimeoutError, ``pass``), then we run one poll,
    then we wait on ``stop`` for ``poll_interval_s`` seconds. Setting stop
    after the first poll lets the wait_for resolve and return cleanly.
    """
    model_store = MagicMock()
    model_store.save_state = AsyncMock()
    model_store.load_state = AsyncMock(return_value=None)

    fake_client = MagicMock()

    async def _gen(*_a: Any, **_kw: Any):
        if False:
            yield  # pragma: no cover

    fake_client.get_objects = _gen
    parser = MagicMock()
    parser.parse = MagicMock(return_value=())

    stop = asyncio.Event()
    poll_count = 0

    consumer = TAXIIFeedConsumer(
        feed_config=TAXIIFeedConfig(
            id="otx",
            url="https://x/",
            collection_id="c",
            poll_interval_s=5,  # large enough we can preempt.
        ),
        defaults=_defaults(startup_jitter_s=0, default_poll_interval_s=5),
        model_store=model_store,
        client=fake_client,
        parser=parser,
        metrics=TAXIIMetricsRegistry(),
        breaker=AuthCircuitBreaker(threshold=3, open_seconds=60, now_fn=lambda: 0.0),
        clock_ns=lambda: 0,
    )

    real_poll = consumer.poll_once

    async def _counting_poll() -> Any:
        nonlocal poll_count
        poll_count += 1
        result = await real_poll()
        # Trigger stop after first poll completes; wait_for(stop, 5.0)
        # should then resolve via the event and trigger ``return``.
        stop.set()
        return result

    consumer.poll_once = _counting_poll  # type: ignore[method-assign]

    await asyncio.wait_for(consumer.run_forever(stop), timeout=2.0)
    assert poll_count == 1
