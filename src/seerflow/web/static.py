"""Mount the built React dashboard as static assets on a FastAPI app.

The dashboard is built by ``npm run build`` in ``frontend/`` and lands in
``src/seerflow/web/dist/``. The wheel bundles that directory via
``[tool.hatch.build.targets.wheel.force-include]``. When the dist directory
is absent (dev checkout without a frontend build, unit tests), the mount is
a no-op so the API still works.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.responses import Response
    from starlette.types import Scope

DEFAULT_DIST = Path(__file__).parent / "dist"
# Backwards-compat alias; callers prefer ``DEFAULT_DIST``. Retained so
# existing ``patch("seerflow.api.app._DEFAULT_DIST", ...)`` tests keep
# working.
_DEFAULT_DIST = DEFAULT_DIST


def _is_api_path(path: str) -> bool:
    """True when ``path`` (as Starlette hands it to the mount) targets the API.

    Starlette strips the mount prefix before invoking ``get_response``,
    leaving the bare prefix (``/api`` with no trailing slash) or the
    full sub-path. Normalize to a lowercase prefix comparison so clients
    cannot smuggle a JSON endpoint behind the SPA fallback.

    Percent-encoded variants (e.g. ``/%61pi/...`` where ``%61`` == 'a',
    or ``/api%2Fv1/...`` where ``%2F`` == '/') are caught by Starlette's
    own URL canonicalization, which decodes the path before dispatching
    the mount. The contract is locked by the bypass test in
    ``test_static.py`` (SEE-245); any future refactor must preserve it.

    Note: leading-double-slash bypass (``//api/...``) is NOT defended
    here — Starlette consumes the duplicated prefix during mount
    routing, so the predicate never sees the ``api/`` segment. Closing
    that gap needs middleware-level path normalization; tracked as a
    separate follow-up.
    """
    clean = path.lstrip("/").lower()
    return clean == "api" or clean.startswith("api/")


class _SpaStaticFiles(StaticFiles):
    """``StaticFiles`` subclass that falls back to ``index.html``.

    A client-side-routed single-page app needs unknown paths to return
    the entry HTML so the router can pick them up. ``StaticFiles``
    raises ``HTTPException(404)`` for missing files; we catch only that
    and return ``index.html``, letting other exceptions propagate.
    Requests to ``/api/*`` propagate the 404 so JSON clients see the
    real error instead of an HTML payload.
    """

    def __init__(self, directory: Path | str) -> None:
        super().__init__(directory=str(directory), html=True)
        self._index = Path(directory) / "index.html"

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and not _is_api_path(path):
                # ``index.html`` must not be cached: the referenced
                # asset hashes change on every deploy.
                return FileResponse(self._index, headers={"Cache-Control": "no-cache"})
            raise


def mount_dashboard(app: FastAPI, dist_dir: Path = DEFAULT_DIST) -> bool:
    """Mount the built dashboard at ``/``.

    Returns ``True`` when mounted, ``False`` when ``dist_dir/index.html`` is
    absent. Call this AFTER registering API routes so ``/api/*`` wins.
    """
    index = dist_dir / "index.html"
    if not index.is_file():
        return False
    app.mount("/", _SpaStaticFiles(dist_dir), name="dashboard")
    return True
