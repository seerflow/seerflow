"""End-to-end: IoCMatcher refresh against the real SQLite ModelStore."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

import msgspec
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


def _ipv4(value: str) -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed="f1",
        confidence=80,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


# coverage.py installs a global trace function that ~2x's wall-clock time.
# AC2 is a developer-laptop benchmark — measure it without trace overhead so
# the gate doesn't shift just because we're collecting coverage.
_UNDER_COVERAGE = sys.gettrace() is not None
_REBUILD_BUDGET_S = 3.0 if _UNDER_COVERAGE else 1.0


@pytest.mark.asyncio
async def test_matcher_rebuilds_within_one_second_for_100k_indicators(
    tmp_path: Path,
) -> None:
    store = await connect_storage(StorageConfig(data_dir=str(tmp_path)))
    try:
        snap = IndicatorSnapshot(
            feed_id="f1",
            fetched_at_ns=1,
            indicators=tuple(_ipv4(f"10.0.{i // 256}.{i % 256}") for i in range(100_000)),
            cursor=None,
        )
        await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))
        cfg = ThreatIntelConfig(
            enabled=True,
            feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
            matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=10),
        )
        matcher = IoCMatcher(config=cfg, model_store=store)
        t0 = time.monotonic()
        await matcher.refresh()
        elapsed = time.monotonic() - t0
        assert elapsed < _REBUILD_BUDGET_S, (
            f"refresh took {elapsed:.2f}s, must be < {_REBUILD_BUDGET_S}s "
            f"(under_coverage={_UNDER_COVERAGE})"
        )
        assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 100_000}
        assert matcher.check("10.0.0.0", "ipv4") is not None
    finally:
        await store.close()
