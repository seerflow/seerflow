"""ASGI middleware that canonicalises request paths.

Collapses runs of ``/`` in ``scope["path"]`` and ``scope["raw_path"]`` to
a single ``/`` before the request reaches Starlette's mount router.
Closes the leading-multi-slash bypass (``GET //api/v1/x`` returning the
SPA index instead of a 404) by ensuring every downstream consumer sees
a canonical path. See SEE-248.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send

_MULTI_SLASH = re.compile(r"/+")


class CollapseSlashesMiddleware:
    """Collapse repeated ``/`` runs in HTTP request paths to a single ``/``.

    Pure ASGI3 callable. No-op on non-HTTP scopes (``lifespan``,
    ``websocket``) and on already-canonical paths. Builds a new
    ``scope`` dict rather than mutating the caller's reference, per
    the project immutability rule.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            if "//" in path:
                collapsed = _MULTI_SLASH.sub("/", path)
                scope = {
                    **scope,
                    "path": collapsed,
                    "raw_path": collapsed.encode("utf-8"),
                }
        await self.app(scope, receive, send)
