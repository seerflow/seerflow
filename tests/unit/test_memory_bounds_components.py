"""S-082 unit tests for per-component ``bounds()`` accessors.

Covers the structures that grew an ``_eviction_count`` slot in this story:
``RiskRegister``, ``KillChainTracker``, ``BaselineStore``, three LLM
caches. Each component is exercised in isolation (no fixtures, no mocks
of the component itself) so the audit invariant — *every LRU drop
increments the counter* — is enforced by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from seerflow.correlation.kill_chain import KillChainTracker
from seerflow.correlation.risk import RiskEntry, RiskRegister
from seerflow.llm.explanation.cache import ExplanationCache
from seerflow.llm.hunt.cache import HuntCache
from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
from seerflow.ueba.baseline import EntityBaseline, UEBAParams
from seerflow.ueba.store import BaselineStore

# ---------------------------------------------------------------------------
# RiskRegister
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_risk_register_bounds_fresh() -> None:
    reg = RiskRegister(half_life_ns=10**9, threshold=10.0, max_entities=4)
    assert reg.bounds() == {"current": 0, "max": 4, "evictions": 0}


@pytest.mark.unit
def test_risk_register_eviction_counter_increments() -> None:
    reg = RiskRegister(half_life_ns=10**9, threshold=10.0, max_entities=3)
    for i in range(7):
        reg.add_risk(
            f"entity-{i}",
            RiskEntry(timestamp_ns=1, risk_points=1.0, source="ml", rule_name="r"),
        )
    bounds = reg.bounds()
    assert bounds == {"current": 3, "max": 3, "evictions": 4}


# ---------------------------------------------------------------------------
# KillChainTracker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeKCConfig:
    enabled: bool = True
    tactic_threshold: int = 100  # set high so threshold alerts don't fire
    window_seconds: int = 86400
    max_entities: int = 3


@dataclass(frozen=True)
class _FakeAlert:
    timestamp_ns: int
    mitre_tactics: tuple[str, ...]
    entity_uuid: str
    alert_id: str = "00000000-0000-0000-0000-000000000000"


@pytest.mark.unit
def test_kill_chain_bounds_fresh() -> None:
    tracker = KillChainTracker(_FakeKCConfig())  # type: ignore[arg-type]
    assert tracker.bounds() == {"current": 0, "max": 3, "evictions": 0}


@pytest.mark.unit
def test_kill_chain_eviction_counter() -> None:
    tracker = KillChainTracker(_FakeKCConfig())  # type: ignore[arg-type]
    for i in range(8):
        tracker.record_alert(
            _FakeAlert(  # type: ignore[arg-type]
                timestamp_ns=1_000_000_000 * (i + 1),
                mitre_tactics=("execution",),
                entity_uuid=f"entity-{i}",
            )
        )
    bounds = tracker.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 5


# ---------------------------------------------------------------------------
# BaselineStore
# ---------------------------------------------------------------------------


def _ueba_params() -> UEBAParams:
    return UEBAParams(
        alpha=0.05,
        source_ip_cap=4,
        template_top_k=4,
        warmup_days=0,
        warmup_min_events=0,
    )


def _make_baseline(entity_uuid: str) -> EntityBaseline:
    """Tiny baseline factory — every field uses a sentinel default; the
    LRU contract has no opinion on contents."""
    return EntityBaseline(
        entity_uuid=entity_uuid,
        entity_type="user",
        first_seen_ns=0,
        last_seen_ns=0,
        event_count=0,
        warmup_complete=False,
        hours=tuple([0] * 24),
        source_ips=(),
        volume_ema_min=0.0,
        volume_ema_hour=0.0,
        volume_last_ns=0,
        templates=(),
    )


@pytest.mark.unit
def test_baseline_store_bounds_fresh() -> None:
    store = BaselineStore(params=_ueba_params(), max_entities=4)
    assert store.bounds() == {"current": 0, "max": 4, "evictions": 0}


@pytest.mark.unit
def test_baseline_store_eviction_counter_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    store = BaselineStore(params=_ueba_params(), max_entities=3)
    # Patch apply_event so we don't need a real SeerflowEvent — the LRU
    # contract is independent of the baseline content.
    monkeypatch.setattr(
        "seerflow.ueba.store.apply_event",
        lambda *, baseline, entity_uuid, entity_type, event, params: _make_baseline(entity_uuid),
    )
    for i in range(7):
        store._learn_one(f"entity-{i}", "user", object())  # type: ignore[arg-type]
    bounds = store.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 4


# ---------------------------------------------------------------------------
# LLM caches (each shares the LRU+TTL contract)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explanation_cache_eviction_counter() -> None:
    from seerflow.llm.explanation.result import ExplanationResult

    cache = ExplanationCache(max_entries=3, ttl_seconds=3600)
    fake = ExplanationResult(
        alert_id="a",
        summary="s",
        anomaly_rationale="",
        contributing_events=(),
        recommended_next_steps=(),
        model="test",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
        truncated=False,
    )
    for i in range(7):
        await cache.put(f"alert-{i}", fake)
    bounds = cache.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hunt_cache_eviction_counter() -> None:
    cache = HuntCache(max_entries=3, ttl_seconds=3600)
    for i in range(7):
        await cache.put(f"query {i}", {"k": "v"})
    bounds = cache.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rule_suggestion_cache_eviction_counter() -> None:
    from seerflow.llm.rule_suggestion.result import RuleSuggestionResult

    cache = RuleSuggestionCache(max_entries=3, ttl_seconds=3600)
    fake = RuleSuggestionResult(
        pattern_key="k",
        tp_count=0,
        yaml="",
        title="",
        logsource_key=(),
        validation_stage="ok",
        validation_message="",
        contributing_alert_ids=(),
        model="test",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
    )
    for i in range(7):
        await cache.put(f"pattern-{i}", fake)
    bounds = cache.bounds()
    assert bounds["current"] == 3
    assert bounds["max"] == 3
    assert bounds["evictions"] == 4
