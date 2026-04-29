"""Unit tests for IoCMatcher (S-068)."""

from __future__ import annotations

import pytest

from seerflow.config import IoCMatcherConfig, ThreatIntelConfig
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
