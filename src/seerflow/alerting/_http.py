"""Shared HTTP post-with-retry helper used by all alerting channels."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_log = logging.getLogger("seerflow")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
# Scrub credential-bearing URL prefixes from log strings. Currently matches
# Telegram's ``/bot<token>/`` pattern — aiohttp exception messages frequently
# echo the request URL, so scrubbing at the log boundary keeps bot tokens out
# of operator log streams.
_SECRET_URL_PATTERNS = (re.compile(r"/bot[^/\s]+/"),)

RetryDecision = Literal["stop", "retry", "default"]


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
    resp: aiohttp.ClientResponse,
    body_text: str,
    masked_for_log: str,
    attempt: int,
) -> bool:
    """Return True when the caller should stop retrying (success or 4xx)."""
    if resp.status < 400:
        return True
    body = sanitize_body(body_text)
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
    body_inspector: Callable[[int, str], RetryDecision] | None = None,
) -> None:
    """POST with exponential backoff.

    4xx -> log-and-drop (no retry). 5xx / network error -> retry up to
    ``attempts`` times. ``masked_for_log`` is the only identifier written to
    logs - never pass a raw URL that contains secrets.
    When ``data`` is provided, it is sent as form-encoded body; otherwise
    ``payload`` is sent as JSON.

    ``body_inspector`` (optional): callback invoked for every non-2xx response
    with ``(status, body_text)``. Returns one of:

    - ``"stop"``  - exit retry loop immediately. The inspector owns any logging.
    - ``"retry"`` - log a warning, sleep the backoff delay, retry.
    - ``"default"`` - fall through to the standard 4xx-stop / 5xx-retry path.

    Inspector exceptions land in the broad ``except`` block below and trigger a
    retry attempt (same as a transport error).
    """
    post_kwargs = _build_post_kwargs(timeout_seconds, headers, auth, payload, data)
    for attempt in range(attempts):
        try:
            async with session.post(url, **post_kwargs) as resp:
                if resp.status < 400:
                    return
                body_text = await resp.text(errors="replace")
                if body_inspector is not None:
                    decision = body_inspector(resp.status, body_text)
                    if decision == "stop":
                        return
                    if decision == "retry":
                        _log.warning(
                            "Channel %s inspector requested retry (attempt %d, status %d)",
                            masked_for_log,
                            attempt + 1,
                            resp.status,
                        )
                    elif await _handle_response(resp, body_text, masked_for_log, attempt):
                        return
                elif await _handle_response(resp, body_text, masked_for_log, attempt):
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
