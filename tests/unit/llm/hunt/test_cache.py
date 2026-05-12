"""Unit tests for ``HuntCache`` (S-072, Task 2)."""

from __future__ import annotations

import asyncio

import pytest

from seerflow.llm.hunt.cache import HuntCache


def _filters(text: str = "ssh") -> dict[str, object]:
    return {"text_query": text}


@pytest.mark.unit
async def test_cache_put_and_get_returns_copy() -> None:
    cache = HuntCache(max_entries=4, ttl_seconds=60)
    await cache.put("ssh from external", _filters("ssh"))
    got = await cache.get("ssh from external")
    assert got == {"text_query": "ssh"}


@pytest.mark.unit
async def test_cache_miss_returns_none() -> None:
    cache = HuntCache(max_entries=4, ttl_seconds=60)
    assert await cache.get("never seen") is None


@pytest.mark.unit
async def test_cache_normalises_whitespace_and_case() -> None:
    cache = HuntCache(max_entries=4, ttl_seconds=60)
    await cache.put("SSH from External", _filters())
    # Different surface form, same intent → same cache key.
    assert await cache.get("  ssh  FROM   external  ") is not None


@pytest.mark.unit
async def test_cache_evicts_least_recently_used() -> None:
    cache = HuntCache(max_entries=2, ttl_seconds=60)
    await cache.put("a", _filters("a"))
    await cache.put("b", _filters("b"))
    # Touch "a" to mark it as most-recently-used.
    assert await cache.get("a") is not None
    await cache.put("c", _filters("c"))
    assert await cache.get("b") is None
    assert await cache.get("a") is not None
    assert await cache.get("c") is not None


@pytest.mark.unit
async def test_cache_ttl_expires_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock = [1000.0]

    def fake_monotonic() -> float:
        return fake_clock[0]

    monkeypatch.setattr("seerflow.llm.hunt.cache.time.monotonic", fake_monotonic)
    cache = HuntCache(max_entries=4, ttl_seconds=5)
    await cache.put("a", _filters("a"))
    assert await cache.get("a") is not None
    fake_clock[0] = 1006.0  # 6s > 5s ttl
    assert await cache.get("a") is None
    assert len(cache) == 0


@pytest.mark.unit
async def test_cache_clear_empties_state() -> None:
    cache = HuntCache(max_entries=4, ttl_seconds=60)
    await cache.put("a", _filters("a"))
    await cache.put("b", _filters("b"))
    assert len(cache) == 2
    await cache.clear()
    assert len(cache) == 0
    assert await cache.get("a") is None


@pytest.mark.unit
async def test_cache_zero_max_entries_disables_storage() -> None:
    cache = HuntCache(max_entries=0, ttl_seconds=60)
    await cache.put("a", _filters("a"))
    assert len(cache) == 0
    assert await cache.get("a") is None


@pytest.mark.unit
def test_cache_rejects_negative_max_entries() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        HuntCache(max_entries=-1, ttl_seconds=60)


@pytest.mark.unit
def test_cache_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        HuntCache(max_entries=4, ttl_seconds=0)


@pytest.mark.unit
async def test_cache_put_existing_key_moves_to_end() -> None:
    cache = HuntCache(max_entries=2, ttl_seconds=60)
    await cache.put("a", _filters("a"))
    await cache.put("b", _filters("b"))
    await cache.put("a", _filters("a"))  # MRU bump
    await cache.put("c", _filters("c"))
    assert await cache.get("b") is None
    assert await cache.get("a") is not None
    assert await cache.get("c") is not None


@pytest.mark.unit
async def test_cache_returned_value_is_independent_copy() -> None:
    """Mutating the returned dict must not affect the stored entry."""
    cache = HuntCache(max_entries=4, ttl_seconds=60)
    stored = {"text_query": "a", "severity_min": 4}
    await cache.put("k", stored)
    got = await cache.get("k")
    assert got is not None
    got["text_query"] = "tampered"
    got2 = await cache.get("k")
    assert got2 == {"text_query": "a", "severity_min": 4}


@pytest.mark.unit
async def test_cache_concurrent_access_safe() -> None:
    cache = HuntCache(max_entries=8, ttl_seconds=60)

    async def writer() -> None:
        for i in range(20):
            await cache.put(f"k{i}", _filters(f"k{i}"))

    async def reader() -> None:
        for i in range(20):
            await cache.get(f"k{i}")

    await asyncio.gather(writer(), reader(), reader())
    assert len(cache) <= 8
