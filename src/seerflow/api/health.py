"""Health endpoint for Docker/Kubernetes liveness and readiness probes."""

from __future__ import annotations

from aiohttp import web


async def health_handler(request: web.Request) -> web.Response:
    """GET /api/v1/health — returns service health status.

    Returns 200 with JSON body when healthy.
    Must complete in < 100ms (no expensive checks).
    """
    body = {
        "status": "healthy",
        "components": {
            "pipeline": "running",
            "storage": "connected",
        },
    }
    return web.json_response(body)


def create_health_app() -> web.Application:
    """Create an aiohttp Application with the health route."""
    app = web.Application()
    app.router.add_get("/api/v1/health", health_handler)
    return app
