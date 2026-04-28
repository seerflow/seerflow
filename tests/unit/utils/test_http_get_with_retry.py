"""Unit tests for get_with_retry (aiohttp GET wrapper)."""

from __future__ import annotations

import aiohttp
import pytest
from aioresponses import aioresponses

from seerflow.utils.http import GetWithRetryError, get_with_retry


@pytest.mark.asyncio
async def test_get_with_retry_returns_body_on_200() -> None:
    url = "https://example.test/r"
    with aioresponses() as m:
        m.get(url, status=200, payload={"ok": True})
        async with aiohttp.ClientSession() as s:
            status, body, _headers = await get_with_retry(
                s, url, max_attempts=3, base_delay_s=0.001
            )
        assert status == 200
        assert body["ok"] is True


@pytest.mark.asyncio
async def test_get_with_retry_retries_on_5xx() -> None:
    url = "https://example.test/r"
    with aioresponses() as m:
        m.get(url, status=503)
        m.get(url, status=503)
        m.get(url, status=200, payload={"ok": True})
        async with aiohttp.ClientSession() as s:
            status, _body, _h = await get_with_retry(s, url, max_attempts=4, base_delay_s=0.001)
        assert status == 200


@pytest.mark.asyncio
async def test_get_with_retry_honors_retry_after() -> None:
    url = "https://example.test/r"
    with aioresponses() as m:
        m.get(url, status=429, headers={"Retry-After": "0"})
        m.get(url, status=200, payload={})
        async with aiohttp.ClientSession() as s:
            status, _b, _h = await get_with_retry(s, url, max_attempts=3, base_delay_s=0.001)
        assert status == 200


@pytest.mark.asyncio
async def test_get_with_retry_raises_after_exhaustion() -> None:
    url = "https://example.test/r"
    with aioresponses() as m:
        m.get(url, status=500)
        m.get(url, status=500)
        async with aiohttp.ClientSession() as s:
            with pytest.raises(GetWithRetryError):
                await get_with_retry(s, url, max_attempts=2, base_delay_s=0.001)


@pytest.mark.asyncio
async def test_get_with_retry_does_not_retry_on_4xx_other_than_429() -> None:
    url = "https://example.test/r"
    with aioresponses() as m:
        m.get(url, status=403)
        async with aiohttp.ClientSession() as s:
            status, _b, _h = await get_with_retry(s, url, max_attempts=3, base_delay_s=0.001)
        assert status == 403  # caller decides
