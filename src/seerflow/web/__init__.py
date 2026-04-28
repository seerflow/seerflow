"""Dashboard static-asset serving for the FastAPI app (S-057)."""

from seerflow.web.middleware import CollapseSlashesMiddleware
from seerflow.web.static import DEFAULT_DIST, mount_dashboard

__all__ = ["DEFAULT_DIST", "CollapseSlashesMiddleware", "mount_dashboard"]
