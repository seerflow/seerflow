"""Shared HTTP post-with-retry helper used by all alerting channels."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = logging.getLogger("seerflow")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def _sanitize_body(raw: str, max_len: int = 200) -> str:
    """Strip control characters and truncate for safe logging."""
    return _CONTROL_CHARS.sub(" ", raw)[:max_len]


async def post_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    payload: Any = None,
    *,
    masked_for_log: str,
    attempts: int = 3,
    delays: Sequence[float] = (1.0, 2.0, 4.0),
    headers: dict[str, str] | None = None,
    auth: aiohttp.BasicAuth | None = None,
    timeout_seconds: float = 10.0,
    data: Any = None,
) -> None:
    """POST with exponential backoff.

    4xx -> log-and-drop (no retry). 5xx / network error -> retry up to
    ``attempts`` times. ``masked_for_log`` is the only identifier written to
    logs - never pass a raw URL that contains secrets.
    When ``data`` is provided, it is sent as form-encoded body; otherwise
    ``payload`` is sent as JSON.
    """
    post_kwargs: dict[str, Any] = {
        "timeout": aiohttp.ClientTimeout(total=timeout_seconds),
        "allow_redirects": False,
    }
    if headers is not None:
        post_kwargs["headers"] = headers
    if auth is not None:
        post_kwargs["auth"] = auth
    if data is not None:
        post_kwargs["data"] = data
    else:
        post_kwargs["json"] = payload

    for attempt in range(attempts):
        try:
            async with session.post(url, **post_kwargs) as resp:
                if resp.status < 400:
                    return
                if resp.status < 500:
                    body = _sanitize_body(await resp.text(errors="replace"))
                    _log.error(
                        "Channel %s returned client error %d - not retrying - response: %s",
                        masked_for_log,
                        resp.status,
                        body,
                    )
                    return
                body = _sanitize_body(await resp.text(errors="replace"))
                _log.warning(
                    "Channel %s returned %d (attempt %d) - response: %s",
                    masked_for_log,
                    resp.status,
                    attempt + 1,
                    body,
                )
        except Exception as exc:
            # CancelledError is BaseException on Py3.8+ so it still propagates.
            # Deliberately broad: any formatter/mock TypeError / OSError from
            # lower transport layers should surface as a retryable attempt, not
            # a pipeline crash (behaviour preserved from the original
            # AlertDispatcher._post_with_retry).
            _log.warning(
                "Channel %s failed (attempt %d): %s",
                masked_for_log,
                attempt + 1,
                exc,
            )
        if attempt < attempts - 1:
            sleep_for = delays[attempt] if attempt < len(delays) else delays[-1]
            await asyncio.sleep(sleep_for)
    _log.error(
        "Channel %s: all %d attempts exhausted without success",
        masked_for_log,
        attempts,
    )
