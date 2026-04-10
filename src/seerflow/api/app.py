"""FastAPI application factory for the Seerflow REST API.

Usage::

    app = create_api_app(log_store=sqlite, alert_store=sqlite)
    # Run with: uvicorn ... --factory seerflow.api.app:create_api_app
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from seerflow.api import ws as ws_module
from seerflow.api.deps import StorageDeps
from seerflow.api.routes import alerts, entities, events, health, stats
from seerflow.api.ws import ConnectionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from seerflow.config import SeerflowConfig
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore

_API_PREFIX = "/api/v1"


def _default_allowed_origins(dashboard_port: int) -> frozenset[str]:
    """Safe-by-default CSWSH origin allowlist for the dashboard port."""
    return frozenset(
        {
            f"http://localhost:{dashboard_port}",
            f"http://127.0.0.1:{dashboard_port}",
        }
    )


def _build_ws_manager(
    alert_store: AlertStore,
    config: SeerflowConfig | None,
) -> ConnectionManager:
    """Construct a ConnectionManager from SeerflowConfig ws_* fields.

    If ``config.ws_allowed_origins`` is empty, a localhost-based default
    allowlist is computed from ``dashboard_port``. When ``config`` is
    ``None`` (tests, direct app construction), no Origin check is applied.
    """
    if config is None:
        return ConnectionManager(alert_store=alert_store)
    allowed_origins: frozenset[str]
    if config.ws_allowed_origins:
        allowed_origins = frozenset(config.ws_allowed_origins)
    else:
        allowed_origins = _default_allowed_origins(config.dashboard_port)
    return ConnectionManager(
        alert_store=alert_store,
        max_connections=config.ws_max_connections,
        queue_maxlen=config.ws_queue_maxlen,
        tick_interval_s=config.ws_tick_interval_s,
        batch_max_events=config.ws_batch_max_events,
        status_interval_s=config.ws_status_interval_s,
        allowed_origins=allowed_origins,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the WebSocket status task on startup and shut down cleanly."""
    app.state.ws_manager.start_status_task()
    try:
        yield
    finally:
        await app.state.ws_manager.shutdown()


def _register_routes(app: FastAPI) -> None:
    """Include all API routers under the configured prefix."""
    app.include_router(events.router, prefix=_API_PREFIX)
    app.include_router(alerts.router, prefix=_API_PREFIX)
    app.include_router(entities.router, prefix=_API_PREFIX)
    app.include_router(health.router, prefix=_API_PREFIX)
    app.include_router(stats.router, prefix=_API_PREFIX)
    app.include_router(ws_module.router, prefix=_API_PREFIX)


def create_api_app(
    log_store: LogStore,
    alert_store: AlertStore,
    entity_store: EntityStore | None = None,
    config: SeerflowConfig | None = None,
    ws_manager: ConnectionManager | None = None,
) -> FastAPI:
    """Create and configure the Seerflow FastAPI application.

    Args:
        log_store: Event persistence backend.
        alert_store: Alert persistence backend.
        entity_store: Optional entity query backend.
        config: Optional application configuration. ``ws_*`` fields are
            applied to the default ``ConnectionManager`` when ``ws_manager``
            is not supplied.
        ws_manager: Optional WebSocket ConnectionManager. A default is
            created from ``config.ws_*`` fields (or hard defaults) if not
            supplied.
    """
    app = FastAPI(
        title="Seerflow API",
        version="1.0.0",
        docs_url=f"{_API_PREFIX}/docs",
        openapi_url=f"{_API_PREFIX}/openapi.json",
        redoc_url=None,
        lifespan=_lifespan,
    )

    app.state.storage = StorageDeps(
        log_store=log_store,
        alert_store=alert_store,
        entity_store=entity_store,
    )
    app.state.config = config
    app.state.health_state = {"pipeline": "running", "storage": "connected"}
    app.state.ws_manager = ws_manager or _build_ws_manager(alert_store, config)

    # CORS — wide open for v1 (localhost-only, no auth).
    # Configurable origins deferred to v2 when auth is added.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(app)
    return app
