"""Unit tests for ``seerflow.llm.rule_suggestion.cache.RuleSuggestionCache``.

Covers AC13: LRU + TTL semantics keyed by ``pattern_key``. Mirrors the
shape of :mod:`tests.unit.llm.explanation.test_cache`.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
from seerflow.llm.rule_suggestion.result import RuleSuggestionResult


def _result(pattern_key: str = "ml:hst-anomaly:ip") -> RuleSuggestionResult:
    return RuleSuggestionResult(
        pattern_key=pattern_key,
        tp_count=3,
        yaml="title: t",
        title="t",
        logsource_key=("authentication",),
        validation_stage="ok",
        validation_message="",
        contributing_alert_ids=("a", "b", "c"),
        model="stub-backend",
        generated_at_ns=time.time_ns(),
        latency_ms=12.5,
        cached=False,
    )


@pytest.mark.asyncio
async def test_get_miss_returns_none() -> None:
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=10)
    assert await cache.get("nope") is None


@pytest.mark.asyncio
async def test_put_then_get_marks_cached() -> None:
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=10)
    fresh = _result()
    await cache.put("ml:x:ip", fresh)
    hit = await cache.get("ml:x:ip")
    assert hit is not None
    assert hit.cached is True
    assert hit.latency_ms == 0.0
    # Underlying payload survives the cached/latency flip.
    assert hit.yaml == fresh.yaml
    assert hit.pattern_key == fresh.pattern_key


@pytest.mark.asyncio
async def test_lru_eviction() -> None:
    cache = RuleSuggestionCache(max_entries=2, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.put("b", _result("b"))
    # Bumps "a" to most-recently-used.
    assert await cache.get("a") is not None
    # Adding "c" should evict the LRU entry — "b" — not the just-touched "a".
    await cache.put("c", _result("c"))
    assert await cache.get("a") is not None
    assert await cache.get("c") is not None
    assert await cache.get("b") is None
    assert len(cache) == 2


@pytest.mark.asyncio
async def test_ttl_prune_on_access() -> None:
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=1)
    await cache.put("a", _result("a"))
    # Sleep slightly past the TTL boundary to force a lazy prune.
    await asyncio.sleep(1.1)
    assert await cache.get("a") is None
    # Stale entry should also be removed from the underlying store.
    assert len(cache) == 0


@pytest.mark.asyncio
async def test_max_entries_zero_disables_cache() -> None:
    cache = RuleSuggestionCache(max_entries=0, ttl_seconds=60)
    await cache.put("a", _result("a"))
    assert len(cache) == 0
    assert await cache.get("a") is None


@pytest.mark.asyncio
async def test_clear_empties() -> None:
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.put("b", _result("b"))
    assert len(cache) == 2
    await cache.clear()
    assert len(cache) == 0


@pytest.mark.asyncio
async def test_delete_pattern_key_removes_entry() -> None:
    """``delete(pattern_key)`` removes a single entry without raising."""
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.delete("a")
    assert await cache.get("a") is None
    # Idempotent — second delete is a no-op.
    await cache.delete("a")
    # Deleting a never-cached key is also safe.
    await cache.delete("never-there")


def test_validates_max_entries() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        RuleSuggestionCache(max_entries=-1, ttl_seconds=10)


def test_validates_ttl_seconds() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        RuleSuggestionCache(max_entries=4, ttl_seconds=0)


@pytest.mark.asyncio
async def test_concurrent_put_does_not_corrupt_order() -> None:
    """Multiple concurrent ``put`` calls land deterministically."""
    cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)

    async def _put(key: str) -> None:
        await cache.put(key, _result(key))

    await asyncio.gather(_put("a"), _put("b"), _put("c"), _put("d"))
    assert len(cache) == 4
    for key in ("a", "b", "c", "d"):
        assert await cache.get(key) is not None
