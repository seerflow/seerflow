"""Tests for TokenBucket async rate limiter (S-163)."""

from __future__ import annotations

import asyncio

import pytest

from seerflow.alerting.channels._ratelimit import TokenBucket


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bucket_allows_burst_without_waiting() -> None:
    bucket = TokenBucket(rate_per_second=1.0, burst=3)
    start = asyncio.get_running_loop().time()
    await bucket.acquire()
    await bucket.acquire()
    await bucket.acquire()
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 0.05


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bucket_blocks_when_empty() -> None:
    bucket = TokenBucket(rate_per_second=20.0, burst=1)
    await bucket.acquire()  # drains bucket
    start = asyncio.get_running_loop().time()
    await bucket.acquire()  # must wait ~0.05s for one refill
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed >= 0.03


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bucket_refills_up_to_burst() -> None:
    bucket = TokenBucket(rate_per_second=100.0, burst=5)
    for _ in range(5):
        await bucket.acquire()
    await asyncio.sleep(0.1)
    start = asyncio.get_running_loop().time()
    for _ in range(5):
        await bucket.acquire()
    elapsed = asyncio.get_running_loop().time() - start
    assert elapsed < 0.05


@pytest.mark.unit
def test_bucket_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="rate_per_second"):
        TokenBucket(rate_per_second=0.0, burst=1)


@pytest.mark.unit
def test_bucket_rejects_zero_burst() -> None:
    with pytest.raises(ValueError, match="burst"):
        TokenBucket(rate_per_second=1.0, burst=0)
