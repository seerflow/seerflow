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

_DEFAULT_DIST = Path(__file__).parent / "dist"


class _SpaStaticFiles(StaticFiles):
    """``StaticFiles`` subclass that falls back to ``index.html``.

    A client-side-routed single-page app needs unknown paths to return
    the entry HTML so the router can pick them up. ``StaticFiles``
    raises ``HTTPException(404)`` for missing files; we catch only that
    and return ``index.html``, letting other exceptions propagate.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=str(directory), html=True)
        self._index = directory / "index.html"

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api/"):
                return FileResponse(self._index)
            raise


def mount_dashboard(app: FastAPI, dist_dir: Path = _DEFAULT_DIST) -> bool:
    """Mount the built dashboard at ``/``.

    Returns ``True`` when mounted, ``False`` when ``dist_dir/index.html`` is
    absent. Call this AFTER registering API routes so ``/api/*`` wins.
    """
    index = dist_dir / "index.html"
    if not index.is_file():
        return False
    app.mount("/", _SpaStaticFiles(dist_dir), name="dashboard")
    return True
