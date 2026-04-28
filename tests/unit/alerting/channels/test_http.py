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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_with_retry_scrubs_telegram_bot_token_from_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """aiohttp exception strings sometimes echo the request URL. The helper
    must scrub credential-bearing path segments before logging.
    """
    import logging

    url = "https://api.telegram.org/bot123456:SECRET/sendMessage"

    class _RaisingSession:
        async def __aenter__(self) -> _RaisingSession:
            raise OSError(f"Cannot connect to {url}")

        async def __aexit__(self, *args: object) -> None:
            return None

    class _FakeSession:
        def post(self, _url: str, **_kwargs: object) -> _RaisingSession:
            return _RaisingSession()

    caplog.set_level(logging.WARNING, logger="seerflow")
    await post_with_retry(
        _FakeSession(),  # type: ignore[arg-type]
        url,
        {"x": 1},
        masked_for_log="telegram/-1",
        attempts=1,
        delays=(0.0,),
    )
    combined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "SECRET" not in combined
    assert "/bot<redacted>/" in combined


@pytest.mark.unit
@pytest.mark.asyncio
async def test_body_inspector_receives_status_and_body() -> None:
    """Inspector is called with (status, body_text) for non-2xx responses."""
    captured: list[tuple[int, str]] = []

    def inspector(status: int, body_text: str) -> str:
        captured.append((status, body_text))
        return "default"

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", status=400, body="oops")
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0,),
                body_inspector=inspector,
            )

    assert captured == [(400, "oops")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_body_inspector_stop_short_circuits_5xx() -> None:
    call_count = 0

    def inspector(status: int, body_text: str) -> str:
        del status, body_text
        return "stop"

    def _capture(url: str, **kwargs: Any) -> aioresponses.CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return aioresponses.CallbackResult(status=503)

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", callback=_capture, repeat=True)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0, 0.0, 0.0),
                body_inspector=inspector,
            )

    assert call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_body_inspector_default_preserves_4xx_drop() -> None:
    call_count = 0

    def inspector(status: int, body_text: str) -> str:
        del status, body_text
        return "default"

    def _capture(url: str, **kwargs: Any) -> aioresponses.CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return aioresponses.CallbackResult(status=400)

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", callback=_capture, repeat=True)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0, 0.0, 0.0),
                body_inspector=inspector,
            )

    assert call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_body_inspector_default_preserves_5xx_retry() -> None:
    call_count = 0

    def inspector(status: int, body_text: str) -> str:
        del status, body_text
        return "default"

    def _capture(url: str, **kwargs: Any) -> aioresponses.CallbackResult:
        del url, kwargs
        nonlocal call_count
        call_count += 1
        return aioresponses.CallbackResult(status=503)

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", callback=_capture, repeat=True)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                attempts=3,
                delays=(0.0, 0.0, 0.0),
                body_inspector=inspector,
            )

    assert call_count == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_body_inspector_not_called_on_2xx() -> None:
    calls: list[int] = []

    def inspector(status: int, body_text: str) -> str:
        del body_text
        calls.append(status)
        return "default"

    with aioresponses() as mock:
        mock.post("https://x.example/endpoint", status=200)
        async with aiohttp.ClientSession() as session:
            await post_with_retry(
                session,
                "https://x.example/endpoint",
                {"alert": "x"},
                masked_for_log="x.example",
                delays=(0.0,),
                body_inspector=inspector,
            )

    assert calls == []
