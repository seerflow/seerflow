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
# Scrub credential-bearing URL prefixes from log strings. Currently matches
# Telegram's ``/bot<token>/`` pattern — aiohttp exception messages frequently
# echo the request URL, so scrubbing at the log boundary keeps bot tokens out
# of operator log streams.
_SECRET_URL_PATTERNS = (re.compile(r"/bot[^/\s]+/"),)


def sanitize_body(raw: str, max_len: int = 200) -> str:
    """Strip control characters and truncate for safe logging."""
    return _CONTROL_CHARS.sub(" ", raw)[:max_len]


# Backwards-compatible private alias (removed in a future release).
_sanitize_body = sanitize_body


def _scrub_secrets(msg: str) -> str:
    """Redact known-secret URL segments from a log string."""
    for pat in _SECRET_URL_PATTERNS:
        msg = pat.sub("/bot<redacted>/", msg)
    return msg


def _build_post_kwargs(
    timeout_seconds: float,
    headers: dict[str, str] | None,
    auth: aiohttp.BasicAuth | None,
    payload: Any,
    data: Any,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": aiohttp.ClientTimeout(total=timeout_seconds),
        "allow_redirects": False,
    }
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth
    if data is not None:
        kwargs["data"] = data
    else:
        kwargs["json"] = payload
    return kwargs


async def _handle_response(
    resp: aiohttp.ClientResponse, masked_for_log: str, attempt: int
) -> bool:
    """Return True when the caller should stop retrying (success or 4xx)."""
    if resp.status < 400:
        return True
    body = sanitize_body(await resp.text(errors="replace"))
    if resp.status < 500:
        _log.error(
            "Channel %s returned client error %d - not retrying - response: %s",
            masked_for_log,
            resp.status,
            body,
        )
        return True
    _log.warning(
        "Channel %s returned %d (attempt %d) - response: %s",
        masked_for_log,
        resp.status,
        attempt + 1,
        body,
    )
    return False


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
    post_kwargs = _build_post_kwargs(timeout_seconds, headers, auth, payload, data)
    for attempt in range(attempts):
        try:
            async with session.post(url, **post_kwargs) as resp:
                if await _handle_response(resp, masked_for_log, attempt):
                    return
        except Exception as exc:
            # CancelledError is BaseException on Py3.8+ so it still propagates.
            # Broad catch preserves legacy AlertDispatcher._post_with_retry
            # behaviour: any transport/formatter error becomes a retryable
            # attempt rather than a pipeline crash.
            _log.warning(
                "Channel %s failed (attempt %d): %s",
                masked_for_log,
                attempt + 1,
                _scrub_secrets(str(exc)),
            )
        if attempt < attempts - 1:
            sleep_for = delays[attempt] if attempt < len(delays) else delays[-1]
            await asyncio.sleep(sleep_for)
    _log.error(
        "Channel %s: all %d attempts exhausted without success",
        masked_for_log,
        attempts,
    )
