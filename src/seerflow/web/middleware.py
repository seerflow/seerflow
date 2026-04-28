"""ASGI middleware that canonicalises request paths.

Collapses runs of ``/`` in ``scope["path"]`` and ``scope["raw_path"]`` to
a single ``/`` before the request reaches Starlette's mount router.
Closes the leading-multi-slash bypass class (``GET //api/v1/x`` ever
reaching the SPA fallback or evading downstream consumers like the
SlowAPI rate limiter that key buckets by ``request.url.path``) by
ensuring every downstream consumer sees a canonical path. See SEE-248.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_MULTI_SLASH_STR = re.compile(r"/+")
_MULTI_SLASH_BYTES = re.compile(rb"/+")


class CollapseSlashesMiddleware:
    """Collapse repeated ``/`` runs in HTTP request paths to a single ``/``.

    Pure ASGI3 callable. No-op on non-HTTP scopes (``lifespan``,
    ``websocket``) and on already-canonical paths. Builds a new
    ``scope`` dict rather than mutating the caller's reference, per
    the project immutability rule.

    ``scope["path"]`` (URL-decoded ``str``) and ``scope["raw_path"]``
    (percent-encoded ``bytes``) are collapsed *independently* with
    ``str``- and ``bytes``-typed regex compiles so non-ASCII
    percent-encoded path segments survive the rewrite untouched —
    decoding ``raw_path`` to UTF-8 and re-encoding from ``path``
    would corrupt e.g. ``%E2%98%83`` into the literal snowman bytes.

    WebSocket scopes are deliberately excluded: Starlette dispatches
    WS handshakes through a separate router that does not share the
    SPA mount, and websockets carry their own path semantics that
    are not affected by the bypass class this middleware closes.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            raw_path: bytes = scope["raw_path"]
            if "//" in path or b"//" in raw_path:
                scope = {
                    **scope,
                    "path": _MULTI_SLASH_STR.sub("/", path),
                    "raw_path": _MULTI_SLASH_BYTES.sub(b"/", raw_path),
                }
        await self.app(scope, receive, send)
