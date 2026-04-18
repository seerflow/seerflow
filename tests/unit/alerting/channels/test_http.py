"""Tests for post_with_retry: shared HTTP retry for channel targets."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from seerflow.alerting._http import post_with_retry


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_succeeds_on_200() -> None:
    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", status=200)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0, 0.0),
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_retries_5xx_then_succeeds() -> None:
    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", status=503)
        mock.post("https://x.example/endpoint", status=200)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0, 0.0),
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_gives_up_after_max_attempts() -> None:
    with aioresponses() as mock:
        for _ in range(3):
            mock.post("https://x.example/endpoint", status=503)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                attempts=3,
                delays=(0.0, 0.0),
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_4xx() -> None:
    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", status=400)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0, 0.0),
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_uses_data_when_provided() -> None:
    # Form-encoded payload (e.g. Twilio).
    captured: dict[str, Any] = {}

    def _capture(url: str, **kwargs: Any) -> aioresponses.CallbackResult:
        del url
        captured.update(kwargs)
        return aioresponses.CallbackResult(status=200)

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", callback=_capture)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                masked_for_log="x.example",
                data={"From": "+1", "To": "+2", "Body": "hi"},
                delays=(0.0,),
            )
    assert "data" in captured
    assert "json" not in captured
