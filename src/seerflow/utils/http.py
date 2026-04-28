"""Shared async GET-with-retry helper.

Mirrors the semantics of ``seerflow.alerting._http.post_with_retry`` for
read-side workloads (TAXII feed polling and any future GET-driven
component). Returns the final response body and headers; the caller
decides whether a non-retryable status (e.g. 401, 404) is an error.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import aiohttp

_log = logging.getLogger("seerflow")


class GetWithRetryError(RuntimeError):
    """Raised after ``max_attempts`` retries all failed.

    ``status`` carries the last HTTP status code observed when the failure
    came from a server response (e.g. exhausted retries on 5xx or, for the
    caller, a non-retryable status the caller decided to escalate). It is
    ``None`` for transport-level failures (DNS, TLS, connection reset, etc.).
    Callers wishing to branch on auth vs transient should switch on this
    integer rather than substring-matching ``str(exc)``.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


async def get_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    auth: aiohttp.BasicAuth | None = None,
    timeout_s: float = 30.0,
    max_attempts: int = 5,
    base_delay_s: float = 1.0,
    jitter_pct: float = 0.2,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    """Async GET with exponential backoff on 429/5xx and network errors.

    Returns ``(status, body, headers)``. ``body`` is the decoded JSON
    payload when ``Content-Type: application/json...`` (or
    ``application/taxii+json...``); otherwise the raw text. Non-retryable
    statuses (401, 403, 404, etc.) are returned to the caller — the caller
    is responsible for routing them to its own error policy (e.g. circuit
    breaker on auth failures).
    """
    last_exc: Exception | None = None
    last_status: int | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with session.get(
                url,
                headers=headers,
                auth=auth,
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
                allow_redirects=False,
            ) as resp:
                if resp.status in _RETRYABLE_STATUSES:
                    last_status = resp.status
                    if attempt < max_attempts:
                        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                        delay = (
                            retry_after
                            if retry_after is not None
                            else _backoff(attempt, base_delay_s, jitter_pct)
                        )
                        _log.warning(
                            "get_with_retry: %s -> %s (attempt %d/%d), sleeping %.2fs",
                            url,
                            resp.status,
                            attempt,
                            max_attempts,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    # Final attempt landed on a retryable status -> exhausted.
                    break
                body = await _decode_body(resp)
                return resp.status, body, dict(resp.headers)
        except (aiohttp.ClientError, TimeoutError) as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = _backoff(attempt, base_delay_s, jitter_pct)
            _log.warning(
                "get_with_retry: %s network error %r (attempt %d/%d), sleeping %.2fs",
                url,
                exc,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise GetWithRetryError(
            f"GET {url} failed after {max_attempts} attempts; last error: {last_exc!r}",
            status=None,
        )
    raise GetWithRetryError(
        f"GET {url} failed after {max_attempts} attempts; last status: {last_status}",
        status=last_status,
    )


def _backoff(attempt: int, base_delay_s: float, jitter_pct: float) -> float:
    raw: float = base_delay_s * float(2 ** (attempt - 1))
    jitter = raw * jitter_pct * random.random()  # noqa: S311 (jitter only, not crypto)
    return raw + jitter


def _parse_retry_after(header: str | None) -> float | None:
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        return None


async def _decode_body(resp: aiohttp.ClientResponse) -> Any:
    ctype = resp.headers.get("Content-Type", "").lower()
    if "json" in ctype:
        return await resp.json(content_type=None)
    return await resp.text()
