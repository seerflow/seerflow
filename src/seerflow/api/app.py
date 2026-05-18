"""FastAPI application factory for the Seerflow REST API.

Usage::

    app = create_api_app(log_store=sqlite, alert_store=sqlite)
    # Run with: uvicorn ... --factory seerflow.api.app:create_api_app
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.cors import CORSMiddleware

from seerflow.api import ws as ws_module
from seerflow.api.anomaly_timeline import AnomalyTimelineRing
from seerflow.api.deps import DetectionEngines, StorageDeps
from seerflow.api.limits import configure_limiter, limiter, resolve_allowed_origins
from seerflow.api.routes import (
    alerts,
    anomaly,
    attack,
    config,
    entities,
    events,
    explanations,
    health,
    hunt,
    sigma,
    stats,
)
from seerflow.api.ws import ConnectionManager
from seerflow.utils.log_sanitize import sanitize_exception
from seerflow.web import DEFAULT_DIST, CollapseSlashesMiddleware, mount_dashboard

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from seerflow.api.latency import StageLatencyTracker
    from seerflow.api.metrics import MetricsProvider
    from seerflow.config import SeerflowConfig
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.llm.explanation.service import AlertExplanationService
    from seerflow.llm.hunt.service import NaturalLanguageHuntService
    from seerflow.llm.rule_suggestion.service import RuleSuggestionService
    from seerflow.models.alert import CorrelationRule
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.sigma.state import SigmaRuleStateStore
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore
    from seerflow.ueba.engine import UEBAEngine
    from seerflow.ueba.store import BaselineStore

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
    timeline_ring: AnomalyTimelineRing | None = None,
) -> ConnectionManager:
    """Construct a ConnectionManager from SeerflowConfig ws_* fields.

    If ``config.ws_allowed_origins`` is empty, a localhost-based default
    allowlist is computed from ``dashboard_port``. When ``config`` is
    ``None`` (tests, direct app construction), no Origin check is applied.
    """
    if config is None:
        return ConnectionManager(alert_store=alert_store, timeline_ring=timeline_ring)
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
        timeline_ring=timeline_ring,
    )


def build_ws_manager(
    alert_store: AlertStore,
    config: SeerflowConfig | None,
    timeline_ring: AnomalyTimelineRing | None = None,
) -> ConnectionManager:
    """Public wrapper over :func:`_build_ws_manager` (S-304).

    ``pipeline.run._run_with_config`` builds the ``ConnectionManager`` +
    ``AnomalyTimelineRing`` itself so it can pass the SAME instance to both
    ``assemble_handler`` (so the live pipeline handler broadcasts) and
    ``create_api_app`` (so the WebSocket route shares the fan-out) — one
    construction site, identical CSWSH/queue/tick wiring as the default
    in-app build.
    """
    return _build_ws_manager(alert_store, config, timeline_ring)


_SIGMA_FLUSH_INTERVAL_S = 60.0


_logger = logging.getLogger(__name__)


async def _sigma_flush_loop(engine: SigmaEngine, interval_s: float) -> None:
    """Background task that flushes accumulated match counters periodically.

    Cancellation is the normal exit path (lifespan shutdown). Any unexpected
    exception is logged but does not propagate — the loop is best-effort
    observability, not a correctness invariant.
    """
    try:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await engine.flush_counters()
            except Exception:
                _logger.warning("Sigma counter flush failed", exc_info=True)
    except asyncio.CancelledError:
        return


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the WebSocket status task on startup and shut down cleanly."""
    app.state.ws_manager.start_status_task()

    sigma_engine: SigmaEngine | None = app.state.engines.sigma_engine
    sigma_state_store: SigmaRuleStateStore | None = getattr(app.state, "sigma_state_store", None)
    flush_task: asyncio.Task[None] | None = None
    if sigma_engine is not None and sigma_state_store is not None:
        await sigma_engine.attach_state_store(sigma_state_store)
        flush_task = asyncio.create_task(_sigma_flush_loop(sigma_engine, _SIGMA_FLUSH_INTERVAL_S))

    try:
        yield
    finally:
        if flush_task is not None:
            flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await flush_task
            if sigma_engine is not None:
                with contextlib.suppress(Exception):
                    await sigma_engine.flush_counters()
        await app.state.ws_manager.shutdown()


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for otherwise-unhandled exceptions (S-080).

    FastAPI installs handlers for its own ``HTTPException`` and Starlette's
    ``RequestValidationError`` automatically; this handler only fires for
    truly unhandled paths (e.g. an ``asyncpg`` connection drop bubbling up
    from a route). It logs a sanitized one-line summary (DSN-bearing
    exception messages are scrubbed by ``sanitize_exception``) and returns
    a generic 500 response so the wire body never carries implementation
    details or credentials.
    """
    _logger.error(
        "unhandled API error on %s %s: %s",
        request.method,
        request.url.path,
        sanitize_exception(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


async def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a 429 response with ``Retry-After`` header.

    ``slowapi`` bundles a default handler but omits ``Retry-After``.
    RFC 7231 §7.1.3 accepts either delay-seconds or an HTTP-date;
    ``limits.RateLimitItem.get_expiry()`` returns the window granularity
    in seconds (e.g. 60 for ``60/minute``), which is a valid
    delay-seconds value.
    """
    if not isinstance(exc, RateLimitExceeded):  # pragma: no cover
        return JSONResponse(
            status_code=500,
            content={"detail": "Unexpected error"},
        )
    limit_wrapper = exc.limit
    if limit_wrapper is None:  # pragma: no cover — slowapi always sets this
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": "60"},
        )
    item = limit_wrapper.limit
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {item}"},
        headers={"Retry-After": str(item.get_expiry())},
    )


def _install_security_middlewares(app: FastAPI, config: SeerflowConfig | None) -> None:
    """Install rate limiter and CORS middleware (S-181).

    ``add_middleware`` reverses insertion order when building the chain,
    so CORS is added LAST here to run FIRST on requests — this lets
    preflight OPTIONS short-circuit before the limiter counts them.

    When ``config`` is ``None`` (direct app construction without config)
    no security middleware is installed — callers must supply a config
    to opt into rate limiting or CORS.
    """
    if config is None:
        # No config → leave module-level limiter in whatever state it
        # was (disabled by default). This preserves direct-construction
        # behaviour for tests that don't need security middleware.
        return

    configure_limiter(config)
    if config.api_rate_limit_enabled:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
        app.add_middleware(SlowAPIMiddleware)

    allowed_origins = resolve_allowed_origins(config)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            # Explicit list — browsers do not expand `*` to
            # `Authorization` for credentialled requests, so enumerate
            # the headers the dashboard actually needs.
            allow_headers=["Content-Type", "Accept", "Authorization"],
        )


def _register_routes(app: FastAPI) -> None:
    """Include all API routers under the configured prefix."""
    app.include_router(events.router, prefix=_API_PREFIX)
    app.include_router(alerts.router, prefix=_API_PREFIX)
    app.include_router(attack.router, prefix=_API_PREFIX)
    app.include_router(config.router, prefix=_API_PREFIX)
    app.include_router(entities.router, prefix=_API_PREFIX)
    app.include_router(explanations.router, prefix=_API_PREFIX)
    app.include_router(health.router, prefix=_API_PREFIX)
    app.include_router(hunt.router, prefix=_API_PREFIX)
    app.include_router(stats.router, prefix=_API_PREFIX)
    app.include_router(anomaly.router, prefix=_API_PREFIX)
    app.include_router(sigma.router, prefix=_API_PREFIX)
    app.include_router(ws_module.router, prefix=_API_PREFIX)


def create_api_app(
    log_store: LogStore,
    alert_store: AlertStore,
    entity_store: EntityStore | None = None,
    config: SeerflowConfig | None = None,
    ws_manager: ConnectionManager | None = None,
    sigma_engine: SigmaEngine | None = None,
    correlation_rules: Sequence[CorrelationRule] = (),
    baseline_store: BaselineStore | None = None,
    ueba_engine: UEBAEngine | None = None,
    sigma_state_store: SigmaRuleStateStore | None = None,
    health_state: dict[str, str] | None = None,
    ensemble: DetectionEnsemble | None = None,
    explanation_service: AlertExplanationService | None = None,
    hunt_service: NaturalLanguageHuntService | None = None,
    rule_suggestion_service: RuleSuggestionService | None = None,
    stage_latency_tracker: StageLatencyTracker | None = None,
    pipeline_metrics_provider: MetricsProvider | None = None,
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
        baseline_store: Optional UEBA ``BaselineStore``.
        ueba_engine: Optional UEBA engine.
        sigma_state_store: Optional Sigma per-rule state store.
        health_state: Mutable status dict shared with the pipeline. When
            supplied, the ``/api/v1/health`` route observes live mutations
            written by the pipeline (S-217). Defaults to a fresh
            ``{"pipeline": "running", "storage": "connected"}`` dict for
            tests and direct construction.
        ensemble: Optional ``DetectionEnsemble`` exposed via
            ``/api/v1/health`` so the response carries the legacy aiohttp
            ``detection`` extra (S-217).
        explanation_service: Optional ``AlertExplanationService`` powering
            the ``POST /api/v1/alerts/{id}/explain`` + ``GET .../explanation``
            endpoints (S-071). ``None`` when the LLM backend is disabled or
            degraded — the routes then return 503.
        hunt_service: Optional ``NaturalLanguageHuntService`` powering the
            ``POST /api/v1/hunt`` endpoint (S-072). ``None`` when the LLM
            backend is disabled or degraded — the route returns 503.
        rule_suggestion_service: Optional ``RuleSuggestionService`` powering
            the ``/api/v1/sigma/rule-suggestions`` endpoints (S-100, FR-066).
            ``None`` when the LLM backend is disabled or degraded — all
            three routes return 503.
        stage_latency_tracker: Optional rolling per-stage latency tracker
            (S-080). When supplied, the ``/api/v1/health`` route surfaces a
            ``latency_ms`` envelope with ``p50``/``p95``/``p99`` per pipeline
            stage. ``None`` (default) → ``latency_ms`` is an empty dict.
        pipeline_metrics_provider: Optional zero-arg callable returning a
            ``PipelineMetrics`` snapshot (S-080). When supplied, both
            ``/api/v1/health`` and ``/api/v1/stats`` surface live throughput,
            uptime, active source count, and model count. ``None`` (default)
            collapses those fields to zero — the historical contract.
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
        ensemble=ensemble,
    )
    app.state.config = config
    app.state.pipeline_metrics_provider = pipeline_metrics_provider
    app.state.stage_latency_tracker = stage_latency_tracker
    app.state.baseline_store = baseline_store
    app.state.ueba_engine = ueba_engine
    app.state.sigma_state_store = sigma_state_store
    app.state.health_state = (
        health_state
        if health_state is not None
        else {"pipeline": "running", "storage": "connected"}
    )
    app.state.explanation_service = explanation_service
    app.state.hunt_service = hunt_service
    app.state.rule_suggestion_service = rule_suggestion_service
    app.state.anomaly_timeline_ring = AnomalyTimelineRing()
    app.state.ws_manager = ws_manager or _build_ws_manager(
        alert_store, config, app.state.anomaly_timeline_ring
    )

    # Install the catch-all handler BEFORE routes are registered so it
    # applies uniformly to every route (rate-limit + CORS handlers are
    # registered later by ``_install_security_middlewares`` — those are
    # narrower than this fallback and run first by FastAPI's specificity
    # rules).
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    _register_routes(app)
    _install_security_middlewares(app, config)
    # Collapse leading-multi-slash request paths (e.g. ``//api/v1/x``)
    # to a canonical single slash before route dispatch. ``add_middleware``
    # reverses insertion order at build time, so this call goes LAST in
    # ``create_api_app`` to run FIRST on the request — every downstream
    # consumer (security middleware, routers, SPA mount) then sees a
    # canonical ``scope["path"]`` (SEE-248).
    app.add_middleware(CollapseSlashesMiddleware)
    # Mount the built React dashboard LAST so API routes (registered above)
    # take precedence over the catch-all ``/`` StaticFiles mount.
    mount_dashboard(app, dist_dir=DEFAULT_DIST)
    return app
