"""End-to-end auth circuit-breaker test for the TAXII feed consumer.

Drives a real ``TAXIIFeedManager`` + ``TAXIIFeedConsumer`` +
``AuthCircuitBreaker`` triple against ``aioresponses``-mocked HTTP
responses with a deterministic clock. Closes S-227 AC3 (Reviewer 1
weak-pass on PR #218: previously the breaker was only exercised against
a ``MagicMock(allow=False)`` and never end-to-end).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from aioresponses import aioresponses

from seerflow.config import (
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.storage import connect_storage
from seerflow.threat_intel.manager import TAXIIFeedManager

if TYPE_CHECKING:
    from pathlib import Path

    from seerflow.storage.protocols import ModelStore
    from seerflow.threat_intel.consumer import TAXIIFeedConsumer


@pytest.fixture(autouse=True)
def _bypass_dns_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "seerflow.threat_intel.dns._resolve_feed_with_private_ip_guard",
        lambda _feed_id, _hostname: "1.1.1.1",
    )


_FEED_URL = "https://taxii.example/v2/"
_OBJECTS_URL = "https://taxii.example/v2/collections/c/objects/"


def _stix_indicator() -> dict[str, str]:
    return {
        "type": "indicator",
        "spec_version": "2.1",
        "id": "indicator--00000000-0000-0000-0000-000000000099",
        "created": "2026-04-01T00:00:00Z",
        "modified": "2026-04-01T00:00:00Z",
        "valid_from": "2026-04-01T00:00:00Z",
        "pattern": "[ipv4-addr:value = '198.51.100.99']",
        "pattern_type": "stix",
    }


async def _build_manager_and_consumer(
    tmp_path: Path,
) -> tuple[TAXIIFeedManager, TAXIIFeedConsumer, ModelStore]:
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(
            TAXIIFeedConfig(
                id="auth-feed",
                url=_FEED_URL,
                collection_id="c",
                poll_interval_s=60,
            ),
        ),
        startup_jitter_s=0,
    )
    storage = await connect_storage(
        StorageConfig(backend="sqlite", sqlite_path=str(tmp_path / "s.db"))
    )
    mgr = TAXIIFeedManager(config=cfg, model_store=storage)
    # Build the session via start() so the static-resolver wiring runs,
    # then cancel and *await* the background tasks so we can drive
    # poll_once() on our own schedule without leaving "Task was destroyed
    # but it is pending!" warnings on the asyncio GC path.
    await mgr.start()
    pending = list(mgr._tasks.values())
    mgr._tasks.clear()
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    consumer = mgr._build_consumer(cfg.feeds[0])
    return mgr, consumer, storage


async def test_three_consecutive_401s_open_breaker_then_close_on_probe_success(
    tmp_path: Path,
) -> None:
    mgr, consumer, storage = await _build_manager_and_consumer(tmp_path)
    try:
        # Inject a controllable clock so we can advance past open_seconds.
        clock_t = [0.0]
        consumer._breaker.now_fn = lambda: clock_t[0]
        with aioresponses() as m:
            # Three 401s — each poll_once should call _classify_failure.
            for _ in range(3):
                m.get(_OBJECTS_URL, status=401)
            for _ in range(3):
                snap = await consumer.poll_once()
                assert snap.indicators == ()
            assert consumer._breaker.is_open() is True
            metrics_after_failures = mgr.metrics.snapshot("auth-feed")
            assert metrics_after_failures.polls_auth_failed_total == 3
            assert metrics_after_failures.circuit_open is True

            # Advance clock past open_seconds — breaker enters half-open.
            clock_t[0] += consumer._breaker.open_seconds + 1.0
            # Probe response: 200 with a valid indicator — breaker closes.
            m.get(
                _OBJECTS_URL,
                status=200,
                payload={"objects": [_stix_indicator()], "more": False},
                headers={"X-TAXII-Date-Added-Last": "2026-04-01T00:00:00.000Z"},
            )
            probe_snap = await consumer.poll_once()
            assert probe_snap.indicators  # non-empty — probe served the indicator
            assert consumer._breaker.is_open() is False
            metrics_after_close = mgr.metrics.snapshot("auth-feed")
            assert metrics_after_close.circuit_open is False
            # Auth-failure counter is cumulative — still 3, not bumped on success.
            assert metrics_after_close.polls_auth_failed_total == 3
            assert metrics_after_close.polls_ok_total == 1
    finally:
        await mgr.stop()
        await storage.close()


async def test_breaker_reopens_when_half_open_probe_returns_401(
    tmp_path: Path,
) -> None:
    mgr, consumer, storage = await _build_manager_and_consumer(tmp_path)
    try:
        clock_t = [0.0]
        consumer._breaker.now_fn = lambda: clock_t[0]
        with aioresponses() as m:
            for _ in range(3):
                m.get(_OBJECTS_URL, status=401)
            for _ in range(3):
                await consumer.poll_once()
            assert consumer._breaker.is_open() is True

            # Advance clock past open_seconds — breaker grants the probe.
            clock_t[0] += consumer._breaker.open_seconds + 1.0
            m.get(_OBJECTS_URL, status=401)
            await consumer.poll_once()
            # Probe failed — breaker re-opens (record_failure on half-open).
            assert consumer._breaker.is_open() is True
            metrics_after_reopen = mgr.metrics.snapshot("auth-feed")
            assert metrics_after_reopen.polls_auth_failed_total == 4
            assert metrics_after_reopen.circuit_open is True
    finally:
        await mgr.stop()
        await storage.close()
