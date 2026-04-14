"""FastAPI application factory for the Seerflow REST API.

Usage::

    app = create_api_app(log_store=sqlite, alert_store=sqlite)
    # Run with: uvicorn ... --factory seerflow.api.app:create_api_app
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from seerflow.api import ws as ws_module
from seerflow.api.deps import DetectionEngines, StorageDeps
from seerflow.api.limits import build_limiter, resolve_allowed_origins
from seerflow.api.routes import (
    alerts,
    attack,
    config,
    entities,
    events,
    health,
    stats,
)
from seerflow.api.ws import ConnectionManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from seerflow.config import SeerflowConfig
    from seerflow.models.alert import CorrelationRule
    from seerflow.sigma.engine import SigmaEngine
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
        filter_min_interval_ns=config.ws_filter_min_interval_ms * 1_000_000,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the WebSocket status task on startup and shut down cleanly."""
    app.state.ws_manager.start_status_task()
    try:
        yield
    finally:
        await app.state.ws_manager.shutdown()


def _install_security_middlewares(
    app: FastAPI, config: SeerflowConfig | None
) -> None:
    """Install rate limiter and CORS middleware (S-181).

    ``add_middleware`` reverses insertion order when building the chain,
    so CORS is added LAST here to run FIRST on requests — this lets
    preflight OPTIONS short-circuit before the limiter counts them.

    When ``config`` is ``None`` (direct app construction without config)
    no security middleware is installed — callers must supply a config
    to opt into rate limiting or CORS.
    """
    if config is None:
        return

    if config.api_rate_limit_enabled:
        limiter = build_limiter(config)
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.add_middleware(SlowAPIMiddleware)

    allowed_origins = resolve_allowed_origins(config)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )


def _register_routes(app: FastAPI) -> None:
    """Include all API routers under the configured prefix."""
    app.include_router(events.router, prefix=_API_PREFIX)
    app.include_router(alerts.router, prefix=_API_PREFIX)
    app.include_router(attack.router, prefix=_API_PREFIX)
    app.include_router(config.router, prefix=_API_PREFIX)
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
    sigma_engine: SigmaEngine | None = None,
    correlation_rules: Sequence[CorrelationRule] = (),
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
        sigma_engine: Optional loaded ``SigmaEngine`` used by the ATT&CK
            coverage endpoint. When ``None``, coverage responses report
            zero rule counts for Sigma rules.
        correlation_rules: Snapshot of correlation rules used by the
            ATT&CK coverage endpoint. Hot reloads are not reflected.
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
    app.state.engines = DetectionEngines(
        sigma_engine=sigma_engine,
        correlation_rules=tuple(correlation_rules),
    )
    app.state.config = config
    app.state.pipeline_metrics_provider = None
    app.state.health_state = {"pipeline": "running", "storage": "connected"}
    app.state.ws_manager = ws_manager or _build_ws_manager(alert_store, config)

    _register_routes(app)
    _install_security_middlewares(app, config)
    return app
