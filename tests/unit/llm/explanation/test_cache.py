"""Unit tests for ``ExplanationCache`` (S-071, Task 4)."""

from __future__ import annotations

import asyncio

import pytest

from seerflow.llm.explanation.cache import ExplanationCache
from seerflow.llm.explanation.result import ExplanationResult


def _result(alert_id: str = "a") -> ExplanationResult:
    return ExplanationResult(
        alert_id=alert_id,
        summary="s",
        anomaly_rationale="r",
        contributing_events=(),
        recommended_next_steps=(),
        model="llama_cpp",
        generated_at_ns=0,
        latency_ms=1.5,
        cached=False,
        truncated=False,
    )


@pytest.mark.unit
async def test_cache_put_and_get_returns_cached_clone() -> None:
    cache = ExplanationCache(max_entries=4, ttl_seconds=60)
    await cache.put("a", _result("a"))
    got = await cache.get("a")
    assert got is not None
    assert got.alert_id == "a"
    # Returned object has ``cached=True`` regardless of the stored value.
    assert got.cached is True
    # Latency on cache hit is reported as 0.0.
    assert got.latency_ms == 0.0


@pytest.mark.unit
async def test_cache_miss_returns_none() -> None:
    cache = ExplanationCache(max_entries=4, ttl_seconds=60)
    assert await cache.get("unknown") is None


@pytest.mark.unit
async def test_cache_evicts_least_recently_used() -> None:
    cache = ExplanationCache(max_entries=2, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.put("b", _result("b"))
    # Touch "a" to mark it as most-recently-used.
    assert await cache.get("a") is not None
    await cache.put("c", _result("c"))
    # "b" should be evicted now, "a" and "c" retained.
    assert await cache.get("b") is None
    assert await cache.get("a") is not None
    assert await cache.get("c") is not None


@pytest.mark.unit
async def test_cache_ttl_expires_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock = [1000.0]

    def fake_monotonic() -> float:
        return fake_clock[0]

    monkeypatch.setattr(
        "seerflow.llm.explanation.cache.time.monotonic",
        fake_monotonic,
    )
    cache = ExplanationCache(max_entries=4, ttl_seconds=5)
    await cache.put("a", _result("a"))
    assert await cache.get("a") is not None
    fake_clock[0] = 1006.0  # 6 s elapsed > 5 s ttl
    assert await cache.get("a") is None
    # Pruned.
    assert len(cache) == 0


@pytest.mark.unit
async def test_cache_clear_empties_state() -> None:
    cache = ExplanationCache(max_entries=4, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.put("b", _result("b"))
    assert len(cache) == 2
    await cache.clear()
    assert len(cache) == 0
    assert await cache.get("a") is None


@pytest.mark.unit
async def test_cache_concurrent_get_put_does_not_raise() -> None:
    cache = ExplanationCache(max_entries=8, ttl_seconds=60)

    async def writer() -> None:
        for i in range(20):
            await cache.put(f"k{i}", _result(f"k{i}"))

    async def reader() -> None:
        for i in range(20):
            await cache.get(f"k{i}")

    await asyncio.gather(writer(), reader(), reader())
    # No KeyError, no corruption — cardinality is bounded by max_entries.
    assert len(cache) <= 8


@pytest.mark.unit
async def test_cache_zero_max_entries_disables_storage() -> None:
    """``max_entries=0`` means the cache is effectively off."""
    cache = ExplanationCache(max_entries=0, ttl_seconds=60)
    await cache.put("a", _result("a"))
    assert len(cache) == 0
    assert await cache.get("a") is None


@pytest.mark.unit
def test_cache_rejects_negative_max_entries() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        ExplanationCache(max_entries=-1, ttl_seconds=60)


@pytest.mark.unit
def test_cache_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        ExplanationCache(max_entries=4, ttl_seconds=0)


@pytest.mark.unit
async def test_cache_put_existing_key_moves_to_end() -> None:
    """Putting an already-present key bumps it to MRU (move_to_end branch)."""
    cache = ExplanationCache(max_entries=2, ttl_seconds=60)
    await cache.put("a", _result("a"))
    await cache.put("b", _result("b"))
    # Re-put "a" — bumps it to MRU. Subsequent insert of "c" should evict
    # "b" (the now-LRU), not "a".
    await cache.put("a", _result("a"))
    await cache.put("c", _result("c"))
    assert await cache.get("b") is None
    assert await cache.get("a") is not None
    assert await cache.get("c") is not None
