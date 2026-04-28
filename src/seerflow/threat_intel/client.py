"""Async TAXII 2.1 wire client.

Thin wrapper over ``aiohttp.ClientSession`` exposing the four endpoints
S-067 needs: discovery, api-roots, collection list, and objects.
``taxii2-client`` was deliberately rejected during brainstorm — it is
sync-only and would block the event loop for multi-MB indicator payloads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from seerflow.utils.http import GetWithRetryError, get_with_retry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import aiohttp

_log = logging.getLogger("seerflow")

_TAXII_ACCEPT = "application/taxii+json;version=2.1"


class TAXIIClient:
    """Read-only TAXII 2.1 client."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        auth_header: dict[str, str] | None = None,
        basic_auth: aiohttp.BasicAuth | None = None,
        timeout_s: float = 30.0,
        max_attempts: int = 5,
        base_delay_s: float = 1.0,
    ) -> None:
        self._session = session
        self._auth_header = dict(auth_header) if auth_header else {}
        self._basic_auth = basic_auth
        self._timeout_s = timeout_s
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s

    async def discover(self, root_url: str) -> dict[str, Any]:
        status, body, _ = await self._get(root_url)
        if status != 200:
            raise GetWithRetryError(f"TAXII discover {root_url} -> {status}")
        return body  # type: ignore[no-any-return]

    async def get_objects(
        self, objects_url: str, *, added_after: str | None
    ) -> AsyncIterator[tuple[dict[str, Any], str | None]]:
        params: dict[str, Any] = {}
        if added_after is not None:
            params["added_after"] = added_after
        url: str | None = objects_url
        while url is not None:
            status, body, headers = await self._get(url, params=params)
            if status == 304:
                return
            if status != 200:
                raise GetWithRetryError(f"TAXII objects {url} -> {status}")
            last_added = headers.get("X-TAXII-Date-Added-Last")
            if not isinstance(body, dict):
                raise GetWithRetryError(f"TAXII objects {url}: non-json body")
            for sdo in body.get("objects", []) or []:
                yield sdo, last_added
            if body.get("more"):
                next_token = body.get("next")
                if not next_token:
                    return
                params = {"next": next_token}
            else:
                return

    async def _get(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> tuple[int, Any, dict[str, str]]:
        headers = {"Accept": _TAXII_ACCEPT, **self._auth_header}
        return await get_with_retry(
            self._session,
            url,
            headers=headers,
            auth=self._basic_auth,
            params=params,
            timeout_s=self._timeout_s,
            max_attempts=self._max_attempts,
            base_delay_s=self._base_delay_s,
        )
