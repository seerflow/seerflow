"""FastAPI application factory for the Seerflow REST API.

Usage::

    app = create_api_app(log_store=sqlite, alert_store=sqlite)
    # Run with: uvicorn ... --factory seerflow.api.app:create_api_app
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from seerflow.api import ws as ws_module
from seerflow.api.deps import StorageDeps
from seerflow.api.routes import alerts, entities, events, health, stats
from seerflow.api.ws import ConnectionManager

if TYPE_CHECKING:
    from seerflow.config import SeerflowConfig
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore

_API_PREFIX = "/api/v1"


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
        config: Optional application configuration.
        ws_manager: Optional WebSocket ConnectionManager. A default is created
            if not supplied.
    """
    app = FastAPI(
        title="Seerflow API",
        version="1.0.0",
        docs_url=f"{_API_PREFIX}/docs",
        openapi_url=f"{_API_PREFIX}/openapi.json",
        redoc_url=None,
    )

    # Storage dependency injection
    app.state.storage = StorageDeps(
        log_store=log_store,
        alert_store=alert_store,
        entity_store=entity_store,
    )
    app.state.config = config
    app.state.health_state = {"pipeline": "running", "storage": "connected"}
    app.state.ws_manager = ws_manager or ConnectionManager(alert_store=alert_store)

    # CORS — wide open for v1 (localhost-only, no auth).
    # Configurable origins deferred to v2 when auth is added.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    app.include_router(events.router, prefix=_API_PREFIX)
    app.include_router(alerts.router, prefix=_API_PREFIX)
    app.include_router(entities.router, prefix=_API_PREFIX)
    app.include_router(health.router, prefix=_API_PREFIX)
    app.include_router(stats.router, prefix=_API_PREFIX)
    app.include_router(ws_module.router, prefix=_API_PREFIX)

    @app.on_event("startup")
    async def _start_ws_status_task() -> None:
        app.state.ws_manager.start_status_task()

    @app.on_event("shutdown")
    async def _stop_ws_manager() -> None:
        await app.state.ws_manager.shutdown()

    return app
