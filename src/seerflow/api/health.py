"""Health endpoint for Docker/Kubernetes liveness and readiness probes.

The handler checks application state injected via ``app["health_state"]``
and returns HTTP 200 when all components are healthy, or HTTP 503 when
any component reports a non-healthy status.
"""

from __future__ import annotations

from aiohttp import web

# Typed app key for health state (avoids string-key deprecation warning).
_HEALTH_STATE_KEY: web.AppKey[dict[str, str]] = web.AppKey("health_state")

# Default state used when no state dict is injected (e.g., in tests).
_DEFAULT_STATE: dict[str, str] = {
    "pipeline": "running",
    "storage": "connected",
}


async def health_handler(request: web.Request) -> web.Response:
    """GET /api/v1/health — returns service health status.

    Reads component statuses from ``request.app["health_state"]``.
    Returns 200 when all components are healthy, 503 otherwise.
    """
    state: dict[str, str] = request.app.get(_HEALTH_STATE_KEY, _DEFAULT_STATE)
    all_healthy = all(v in ("running", "connected", "ok") for v in state.values())
    status = "healthy" if all_healthy else "degraded"
    http_status = 200 if all_healthy else 503
    return web.json_response(
        {"status": status, "components": state},
        status=http_status,
    )


def create_health_app(
    state: dict[str, str] | None = None,
) -> web.Application:
    """Create an aiohttp Application with the health route.

    Args:
        state: Mutable dict of component → status. The handler reads this
            on each request. Pass ``None`` for default (all healthy).
    """
    app = web.Application()
    app[_HEALTH_STATE_KEY] = state if state is not None else dict(_DEFAULT_STATE)
    app.router.add_get("/api/v1/health", health_handler)
    return app
