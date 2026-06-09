"""Shared HTTP post-with-retry helper used by all alerting channels."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Literal

import aiohttp

if TYPE_CHECKING:
    import ssl
    from collections.abc import Callable, Sequence

_log = logging.getLogger("seerflow")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
# Scrub credential-bearing fragments from log strings. Patterns:
#   - Telegram's ``/bot<token>/`` URL prefix.
#   - ``Bearer <token>`` Authorization-header values (defence in depth — current
#     aiohttp ``str(exc)`` does not echo headers, but a future version or a
#     wrapper may, and the WhatsApp channel relies on this header for auth).
#   - ``Splunk <token>`` Authorization-header values (S-362 — the Splunk HEC sink
#     authenticates with this scheme; same defence-in-depth rationale as Bearer).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"/bot[^/\s]+/"), "/bot<redacted>/"),
    (re.compile(r"Bearer\s+\S+"), "Bearer <redacted>"),
    (re.compile(r"Splunk\s+\S+"), "Splunk <redacted>"),
)

RetryDecision = Literal["stop", "retry", "default"]


def sanitize_body(raw: str, max_len: int = 200) -> str:
    """Strip control characters and truncate for safe logging."""
    return _CONTROL_CHARS.sub(" ", raw)[:max_len]


# Backwards-compatible private alias (removed in a future release).
_sanitize_body = sanitize_body


def _scrub_secrets(msg: str) -> str:
    """Redact known-secret URL or header fragments from a log string."""
    for pat, replacement in _SECRET_PATTERNS:
        msg = pat.sub(replacement, msg)
    return msg


def _build_post_kwargs(
    timeout_seconds: float,
    headers: dict[str, str] | None,
    auth: aiohttp.BasicAuth | None,
    payload: Any,
    data: Any,
    ssl_context: ssl.SSLContext | None,
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
    # An explicit SSLContext (e.g. a custom CA bundle for a private Splunk HEC)
    # is passed through to aiohttp. ``None`` means aiohttp's default system-trust
    # verification — never disabled here.
    if ssl_context is not None:
        kwargs["ssl"] = ssl_context
    return kwargs


def _handle_response(
    resp: aiohttp.ClientResponse,
    body_text: str,
    masked_for_log: str,
    attempt: int,
) -> bool:
    """Return True when the caller should stop retrying (4xx).

    Pre-condition: ``resp.status >= 400``. The caller (``post_with_retry``)
    short-circuits 2xx responses before this is invoked, so the success branch
    no longer lives here. Synchronous because the body is already in hand —
    the caller reads ``resp.text()`` once and passes the string through.
    """
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
    ssl_context: ssl.SSLContext | None = None,
    body_inspector: Callable[[int, str], RetryDecision] | None = None,
) -> None:
    """POST with exponential backoff.

    4xx -> log-and-drop (no retry). 5xx / network error -> retry up to
    ``attempts`` times. ``masked_for_log`` is the only identifier written to
    logs - never pass a raw URL that contains secrets.
    When ``data`` is provided, it is sent as the raw body; otherwise
    ``payload`` is sent as JSON. ``ssl_context`` (optional): a custom
    :class:`ssl.SSLContext` (e.g. a private CA bundle) passed straight to
    aiohttp; ``None`` keeps aiohttp's default system-trust verification.

    ``body_inspector`` (optional): callback invoked for every non-2xx response
    with ``(status, body_text)``. Returns one of:

    - ``"stop"``  - exit retry loop immediately. The inspector owns any logging.
    - ``"retry"`` - log a warning, sleep the backoff delay, retry.
    - ``"default"`` - fall through to the standard 4xx-stop / 5xx-retry path.

    Inspector exceptions land in the broad ``except`` block below and trigger a
    retry attempt (same as a transport error).
    """
    post_kwargs = _build_post_kwargs(timeout_seconds, headers, auth, payload, data, ssl_context)
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
                    elif _handle_response(resp, body_text, masked_for_log, attempt):
                        return
                elif _handle_response(resp, body_text, masked_for_log, attempt):
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
