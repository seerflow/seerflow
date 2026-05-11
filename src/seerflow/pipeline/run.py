"""Pipeline startup and run functions."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import ssl as _ssl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import uvicorn

from seerflow import __version__
from seerflow.api.app import create_api_app
from seerflow.config import SeerflowConfig, load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline import build_pipeline
from seerflow.pipeline.handler import make_handler
from seerflow.storage import connect_storage
from seerflow.threat_intel import IoCMatcher, TAXIIFeedManager
from seerflow.threat_intel.enricher import _IoCEnrichmentCounters
from seerflow.ueba.engine import UEBAEngine
from seerflow.ueba.store import BaselineStore
from seerflow.web import DEFAULT_DIST

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Protocol

    from fastapi import FastAPI

    from seerflow.alerting.router import NotificationRouter
    from seerflow.api.ws import ConnectionManager
    from seerflow.config import AlertingConfig

    class _StoppablePipeline(Protocol):
        """Subset of the pipeline contract the shutdown closure needs."""

        async def stop(self) -> None: ...

    class _ExitableServer(Protocol):
        """Subset of ``uvicorn.Server`` the shutdown closure needs."""

        should_exit: bool
        force_exit: bool


_log = logging.getLogger("seerflow")


@dataclass
class _ShutdownContext:
    """Handler-owned mutable state for the SIGINT/SIGTERM closure.

    Field semantics:
    - ``pipeline`` — set at construction; the runner whose ``stop()`` the
      handler schedules.
    - ``server`` — starts as ``None``; the caller assigns it AFTER
      ``uvicorn.Server`` is constructed. The closure tolerates ``server is
      None`` so a signal that arrives during the registration→server-build
      window still stops the pipeline (no regression vs. pre-S-218 behaviour).
    - ``fired`` and ``task`` — handler-owned; do NOT write from outside the
      closure. They guarantee the closure is idempotent on the loop thread.
    """

    pipeline: _StoppablePipeline
    server: _ExitableServer | None = None
    fired: bool = False
    task: asyncio.Task[None] | None = None


@contextlib.contextmanager
def _noop_capture_signals(*_args: object, **_kwargs: object) -> Generator[None, None, None]:
    """Replacement for ``uvicorn.Server.capture_signals`` that does nothing.

    Modern uvicorn (>=0.20) installs SIGINT/SIGTERM handlers via this context
    manager when ``Server.serve()`` runs. Seerflow owns the signal chain via
    :func:`_install_shutdown_handlers`, so the uvicorn capture is suppressed
    by patching this no-op onto the bound method. Bypassing uvicorn's
    ``capture_signals`` also bypasses its LIFO re-raise and double-Ctrl-C
    ``force_exit`` escalation — seerflow drives shutdown synchronously from
    its own handler, so neither is needed.

    Accepts arbitrary args so it stays compatible whether uvicorn calls it
    bound (``server.capture_signals()``) or unbound (``server.capture_signals
    = _noop_capture_signals`` then ``self.capture_signals()`` — Python passes
    ``self`` as the first positional arg).
    """
    yield


def _log_shutdown_task_exception(task: asyncio.Task[None]) -> None:
    """``add_done_callback`` hook for the ``pipeline.stop()`` task.

    Logs unexpected exceptions at WARNING so a silent failure inside
    ``pipeline.stop()`` does not become an "unretrieved task" warning at GC
    time. Cancellation is the expected exit when seerflow itself cancels the
    task during cleanup; suppress that case.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _log.warning("pipeline.stop() raised during signal handling", exc_info=exc)


def _install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    pipeline: _StoppablePipeline,
) -> _ShutdownContext:
    """Register SIGINT/SIGTERM handlers that flip uvicorn's exit flag and stop the pipeline.

    The handler is registered EARLY (right after the pipeline is built) so a
    SIGTERM that arrives during dashboard startup still reaches the pipeline.
    The ``server`` reference is filled in by the caller via the returned
    ``_ShutdownContext`` once ``uvicorn.Server`` is constructed; the closure
    tolerates ``ctx.server is None`` (signal arrived too early).

    Uvicorn's ``Server.serve()`` enters ``self.capture_signals()`` by default
    (the modern equivalent of the legacy ``install_signal_handlers``). Callers
    MUST replace ``server.capture_signals`` with :func:`_noop_capture_signals`
    before scheduling ``server.serve()`` or our chain will be silently
    overwritten from inside uvicorn's setup.
    """
    ctx = _ShutdownContext(pipeline=pipeline)
    if sys.platform == "win32":  # pragma: no cover -- Windows uses uvicorn defaults
        return ctx

    import signal as _signal

    def _request_shutdown() -> None:
        if ctx.fired:
            # Second signal during ongoing shutdown — escalate to uvicorn's
            # force_exit (skip graceful drain). Restores the Ctrl-C-twice
            # fast-path that uvicorn's own handler chain would otherwise
            # provide; lost when seerflow took ownership via
            # ``capture_signals = _noop_capture_signals``.
            if ctx.server is not None and not ctx.server.force_exit:
                _log.warning("Second shutdown signal received — forcing exit")
                ctx.server.force_exit = True
            return
        ctx.fired = True
        _log.info("Shutdown signal received — draining uvicorn + pipeline")
        if ctx.server is not None:
            ctx.server.should_exit = True
        ctx.task = asyncio.create_task(pipeline.stop())
        ctx.task.add_done_callback(_log_shutdown_task_exception)

    for sig in (_signal.SIGINT, _signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    return ctx


async def _build_channel_session_and_router(
    alerting: AlertingConfig,
) -> tuple[aiohttp.ClientSession | None, NotificationRouter | None]:
    """Construct an HTTP session + NotificationRouter for multi-channel delivery.

    Returns ``(None, None)`` when no channel targets or routing rules are
    configured, so ``run.py`` falls back to the legacy webhook-only
    dispatcher fan-out path introduced in S-047.

    An ``aiohttp.ClientSession`` is only allocated when at least one HTTP-using
    channel (SMS, Telegram, WhatsApp) is configured. Email uses its own SMTP
    connection and does not require the shared HTTP session.
    """
    from seerflow.alerting.channels import bind_http_channel
    from seerflow.alerting.router import NotificationRouter

    needs_router = bool(
        alerting.email_targets
        or alerting.sms_targets
        or alerting.telegram_targets
        or alerting.whatsapp_targets
        or alerting.routing_rules
    )
    if not needs_router:
        return None, None

    session: aiohttp.ClientSession | None = None
    if alerting.sms_targets or alerting.telegram_targets or alerting.whatsapp_targets:
        connector = aiohttp.TCPConnector(
            ssl=_ssl.create_default_context(),
            limit_per_host=10,
        )
        session = aiohttp.ClientSession(connector=connector)

    # mypy: _HttpChannel Protocol declares ``name``/``min_severity`` as
    # settable but the channel dataclasses are frozen; this is a structural-
    # vs-nominal mismatch in the existing Protocol, not a real issue here.
    channel_targets: list[object] = list(alerting.email_targets)
    if session is not None:
        for sms in alerting.sms_targets:
            channel_targets.append(bind_http_channel(sms, session=session))  # type: ignore[arg-type]
        for tg in alerting.telegram_targets:
            channel_targets.append(bind_http_channel(tg, session=session))  # type: ignore[arg-type]
        for wa in alerting.whatsapp_targets:
            channel_targets.append(bind_http_channel(wa, session=session))  # type: ignore[arg-type]

    router = NotificationRouter(
        targets=channel_targets,  # type: ignore[arg-type]
        rules=alerting.routing_rules,
        default_routing=alerting.default_routing,
        quiet_hours_by_channel=dict(alerting.quiet_hours_by_channel),
    )
    return session, router


async def _serve_or_hint(server: uvicorn.Server, host: str, port: int) -> None:
    """Run the uvicorn server and emit a helpful hint on EADDRINUSE.

    Logs ``Dashboard listening`` once uvicorn has reported it is started
    (``server.started`` flips after the listening socket binds), so users
    do not see a misleading "listening" line followed by an EADDRINUSE
    error a moment later. The error is re-raised so the calling task
    surfaces a non-zero exit via ``asyncio.wait(..., FIRST_COMPLETED)``
    (S-217).
    """
    ready_task = asyncio.create_task(_log_when_started(server, host, port))
    try:
        await server.serve()
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            _log.error(
                "Dashboard port %d already in use; set dashboard_port to a free "
                "port in seerflow.yaml or stop the conflicting process.",
                port,
            )
        raise
    finally:
        ready_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ready_task


async def _log_when_started(server: uvicorn.Server, host: str, port: int) -> None:
    """Emit a single info log line once uvicorn finishes binding."""
    while not server.started:
        await asyncio.sleep(0.05)
    _log.info("Dashboard listening on http://%s:%d/", host, port)


async def _run_with_config(
    config: SeerflowConfig,
    *,
    make_api_app: Callable[..., FastAPI] = create_api_app,
) -> None:
    """Run the pipeline with a pre-built config.

    ``make_api_app`` is a test seam (S-217) so unit tests can stub the
    FastAPI factory without spinning up real uvicorn. Production callers
    should leave the default in place.
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # Reconfigure at user's chosen level
    logging.getLogger().setLevel(getattr(logging, config.log_level, logging.INFO))
    # Suppress noisy third-party loggers
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("drain3").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    _log.info("Seerflow %s starting", __version__)

    # Connect storage
    data_dir = Path(config.storage.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    storage = await connect_storage(config.storage)
    _log.info("Storage: %s", config.storage.sqlite_path)

    # Threat-intel TAXII feed manager (S-067). Constructed unconditionally
    # so the shutdown path can call ``stop()`` without a None-check; the
    # ``start()`` call returns ``[]`` immediately when ``threat_intel.enabled``
    # is False (no aiohttp session opened, no tasks scheduled).
    taxii_manager = TAXIIFeedManager(
        config=config.threat_intel,
        model_store=storage,
    )
    # IoC matcher (S-068). Constructed before manager.start() so the snapshot
    # listener is registered atomically with the consumer fan-out — any
    # snapshot persisted during initial poll will trigger a matcher rebuild.
    ioc_matcher: IoCMatcher | None = None
    if config.threat_intel.matcher.enabled:
        ioc_matcher = IoCMatcher(
            config=config.threat_intel,
            model_store=storage,
        )
        taxii_manager.register_snapshot_listener(ioc_matcher.on_snapshot_updated)
        await ioc_matcher.start()
    ioc_enrichment_counters = _IoCEnrichmentCounters() if ioc_matcher is not None else None
    taxii_failed = await taxii_manager.start()
    if taxii_failed:
        _log.warning(
            "Threat intel: %d feed(s) failed to start: %s",
            len(taxii_failed),
            ", ".join(taxii_failed),
        )
    elif config.threat_intel.enabled:
        _log.info("Threat intel: %d feed(s) running", len(taxii_manager.feed_ids()))

    ensemble = DetectionEnsemble(config.detection)
    try:
        loaded = await ensemble.load_all_state(storage)
        if loaded > 0:
            _log.info("Restored %d model states from storage", loaded)
    except Exception:
        _log.warning("Failed to restore model state — starting fresh", exc_info=True)

    # UEBA baseline store — feature-flag gated by config.ueba.enabled.
    baseline_store: BaselineStore | None = None
    ueba_engine: UEBAEngine | None = None
    if config.ueba.enabled:
        from seerflow.ueba.baseline import UEBAParams

        ueba_params = UEBAParams(
            alpha=config.ueba.ema_alpha,
            source_ip_cap=config.ueba.source_ip_cap,
            template_top_k=config.ueba.template_top_k,
            warmup_days=config.ueba.warmup_days,
            warmup_min_events=config.ueba.warmup_min_events,
        )
        baseline_store = BaselineStore(
            params=ueba_params,
            max_entities=config.ueba.max_entities,
        )
        try:
            restored = await baseline_store.restore(storage)
            _log.info("UEBA: restored %d baselines", restored)
        except Exception:
            _log.warning("UEBA baseline restore failed", exc_info=True)
        ueba_engine = UEBAEngine(config=config.ueba)

    from seerflow.detection.attack_mapping import AttackMapper

    try:
        if config.detection.attack_mappings:
            attack_mapper = AttackMapper.from_config(list(config.detection.attack_mappings))
            _log.info("ATT&CK mapper: %d user-defined mappings", len(attack_mapper))
        else:
            attack_mapper = AttackMapper.load_defaults()
            _log.info("ATT&CK mapper: %d default mappings", len(attack_mapper))
    except (ValueError, OSError) as exc:
        _log.error("ATT&CK mapper init failed — falling back to defaults: %s", exc)
        attack_mapper = AttackMapper.load_defaults()
    if len(attack_mapper) == 0:
        _log.warning("ATT&CK mapper has 0 mappings — ML alerts will have empty MITRE fields")

    try:
        pipeline = await build_pipeline(config)
    except RuntimeError as exc:
        _log.error("Startup failed: %s", exc)
        _log.error(
            "Suggestions:\n"
            "  - Check file permissions for configured log paths\n"
            "  - Ensure ports are not already in use\n"
            "  - Verify receiver settings in seerflow.yaml"
        )
        # Mirror the documented shutdown order (see end of run_pipeline):
        # stop the IoC matcher before TAXII so its debounce loop is cancelled
        # before consumers exit, and no late rebuild fires after teardown.
        if ioc_matcher is not None:
            await ioc_matcher.stop()
        await taxii_manager.stop()
        await storage.close()
        sys.exit(1)

    # Startup banner — only list healthy receivers
    receivers = [sid for sid, r in pipeline.manager._receivers.items() if r.is_healthy()]
    _log.info("Receivers: %s", ", ".join(receivers) if receivers else "none")

    # Graceful shutdown — register SIGINT/SIGTERM handlers that will flip uvicorn's
    # ``should_exit`` flag and stop the pipeline once the server is wired in below.
    shutdown_ctx = _install_shutdown_handlers(asyncio.get_running_loop(), pipeline)

    # Load Sigma rules — degrade gracefully if loading fails
    from seerflow.sigma.engine import SigmaEngine

    sigma_engine: SigmaEngine | None = None
    try:
        _sigma = SigmaEngine()
        _sigma.load_bundled()
        if config.detection.sigma_rules_dirs:
            _sigma.load_custom(list(config.detection.sigma_rules_dirs))
        _log.info("Sigma: %d rules loaded", _sigma.rule_count)
        sigma_engine = _sigma
    except Exception:
        _log.warning("Sigma rule loading failed — running without Sigma detection", exc_info=True)

    # Build entity graph and load persisted edges
    from seerflow.graph.entity_graph import EntityGraph

    entity_graph = EntityGraph()
    try:
        edge_rows = await storage.load_edges()
        entity_graph.load(edge_rows)
        _log.info("Graph: loaded %d edges", len(edge_rows))
    except Exception:
        _log.warning("Graph edge loading failed — starting with empty graph", exc_info=True)
    storage.set_entity_graph(entity_graph)

    # Build graph-structural evaluator for community-crossing / betweenness / fan-out
    from seerflow.correlation.graph_structural import GraphStructuralEvaluator

    graph_structural = GraphStructuralEvaluator(config.detection.graph_structural, entity_graph)
    _log.info("Graph-structural evaluator: enabled")

    # Build kill-chain tracker for ATT&CK tactic progression detection
    from seerflow.correlation.kill_chain import KillChainTracker

    kill_chain_tracker: KillChainTracker | None = None
    if config.detection.kill_chain.enabled:
        kill_chain_tracker = KillChainTracker(config.detection.kill_chain)
        _log.info(
            "Kill-chain tracker: threshold=%d, window=%ds",
            config.detection.kill_chain.tactic_threshold,
            config.detection.kill_chain.window_seconds,
        )

    # Build entity window buffer for temporal correlation
    from seerflow.correlation.window import EntityWindowBuffer

    window_buffer = EntityWindowBuffer(
        window_ns=config.correlation.window_duration_seconds * 1_000_000_000,
        max_events=config.correlation.max_events_per_entity,
        max_entities=config.correlation.max_entities,
    )

    # Build watermark for late-arrival tolerance
    from seerflow.correlation.watermark import Watermark

    watermark = Watermark(
        tolerance_ns=config.correlation.late_tolerance_seconds * 1_000_000_000,
    )

    # Build risk register for per-entity risk accumulation
    from seerflow.correlation.risk import RiskRegister

    risk_register = RiskRegister(
        half_life_ns=config.detection.risk_half_life_hours * 3600 * 1_000_000_000,
        threshold=config.detection.risk_threshold,
        max_entities=config.detection.risk_max_entities,
    )

    # Load correlation rules — bundled + user-configured directories
    from seerflow.correlation.bundled import get_bundled_rule_dir
    from seerflow.correlation.rule_loader import load_correlation_rules

    bundled_dir = str(get_bundled_rule_dir())
    rule_dirs = (bundled_dir, *config.correlation.rule_dirs)
    correlation_rules = load_correlation_rules(rule_dirs)
    _log.info(
        "Correlation: loaded %d rules from %d dirs",
        len(correlation_rules),
        len(rule_dirs),
    )

    # Build correlation engine for real-time rule evaluation
    from seerflow.correlation.engine import CorrelationEngine

    correlation_engine = CorrelationEngine(
        rules=correlation_rules,
        window=window_buffer,
    )
    _log.info("Correlation engine: %d rules loaded", len(correlation_rules))

    from seerflow.correlation.holders import EngineHolder

    sigma_holder = EngineHolder(engine=sigma_engine)
    correlation_holder: EngineHolder[CorrelationEngine | None] = EngineHolder(
        engine=correlation_engine
    )

    # Start rule reloader for user-configured directories
    from seerflow.correlation.reloader import RuleReloader

    reloader = RuleReloader(
        correlation_holder=correlation_holder,
        correlation_dirs=[bundled_dir, *config.correlation.rule_dirs],
        window_buffer=window_buffer,
    )
    reload_task = asyncio.create_task(reloader.watch())

    # Mount FastAPI dashboard + REST + WebSocket on dashboard_port via
    # uvicorn (S-217). The legacy aiohttp ``health_app`` was deleted —
    # the FastAPI ``/api/v1/health`` route mirrors its contract.
    #
    # ``ws_manager`` is intentionally left as ``None`` so the factory
    # builds it via ``_build_ws_manager(...)``, which honours every
    # ``config.ws_*`` field (including the CSWSH ``allowed_origins``
    # check). After ``create_api_app`` returns, read the constructed
    # manager off ``app.state`` and reuse it for ``make_handler`` so
    # the pipeline and the FastAPI route share the same fan-out.

    health_state: dict[str, str] = {"pipeline": "running", "storage": "connected"}
    api_app = make_api_app(
        log_store=storage,
        alert_store=storage,
        entity_store=storage,
        config=config,
        ws_manager=None,
        sigma_engine=sigma_engine,
        correlation_rules=tuple(correlation_rules),
        baseline_store=baseline_store,
        ueba_engine=ueba_engine,
        sigma_state_store=storage,
        health_state=health_state,
        ensemble=ensemble,
    )
    ws_manager: ConnectionManager = api_app.state.ws_manager
    uvicorn_config = uvicorn.Config(
        app=api_app,
        host=config.health_bind_address,
        port=config.dashboard_port,
        loop="asyncio",
        lifespan="on",
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    # Prevent uvicorn from overwriting seerflow's signal handlers from inside
    # ``Server.serve()`` — seerflow owns the signal chain (see _install_shutdown_handlers).
    # Modern uvicorn (>=0.20) uses ``capture_signals()`` instead of the older
    # ``install_signal_handlers``; replacing it with a no-op context manager
    # neutralises the override without touching uvicorn's internal state.
    if not hasattr(server, "capture_signals"):  # pragma: no cover -- uvicorn API changed
        _log.warning(
            "uvicorn.Server.capture_signals not found — uvicorn version may have "
            "changed its signal-install API; seerflow's shutdown handler may be "
            "overridden by uvicorn's default."
        )
    server.capture_signals = _noop_capture_signals  # type: ignore[method-assign]
    # Wire the live server reference into the shared shutdown context so any
    # subsequent SIGTERM flips ``should_exit`` synchronously.
    shutdown_ctx.server = server
    # Late catch-up — if a SIGTERM already fired during the registration→
    # server-build window, the closure stopped the pipeline but could not flip
    # ``should_exit``. Do it now so uvicorn drains as soon as it starts.
    if shutdown_ctx.fired:
        server.should_exit = True
    server_task = asyncio.create_task(
        _serve_or_hint(server, config.health_bind_address, config.dashboard_port),
        name="seerflow.api.server",
    )
    if not (DEFAULT_DIST / "index.html").is_file():
        _log.info(
            "Dashboard bundle missing — run 'cd frontend && npm run build' to "
            "enable the UI. API and WebSocket are still available at /api/v1/*."
        )

    _log.info("Pipeline running — Ctrl+C to stop")
    save_interval_ns = config.detection.model_save_interval_seconds * 1_000_000_000

    from seerflow.alerting.dispatcher import (
        AlertDispatcher,
        build_webhook_delivery_targets,
    )

    webhook_session: aiohttp.ClientSession | None = None
    dispatcher: AlertDispatcher | None = None
    _dispatcher_task: asyncio.Task[None] | None = None
    webhook_targets = config.alerting.webhook_targets
    channel_session, router = await _build_channel_session_and_router(config.alerting)
    if webhook_targets or router is not None:
        if channel_session is not None:
            webhook_session = channel_session
        else:
            _webhook_connector = aiohttp.TCPConnector(
                ssl=_ssl.create_default_context(),
                limit_per_host=10,
            )
            webhook_session = aiohttp.ClientSession(connector=_webhook_connector)
        dispatcher = AlertDispatcher(
            webhook_targets,
            webhook_session,
            dashboard_url=config.alerting.dashboard_url,
            router=router,
        )
        if router is not None and webhook_targets:
            for adapter in build_webhook_delivery_targets(dispatcher):
                router.register_target(adapter)
        _dispatcher_task = asyncio.create_task(dispatcher.run())
        _log.info(
            "Alert dispatcher: %d webhook target(s), router=%s",
            len(webhook_targets),
            "enabled" if router is not None else "disabled",
        )

    from seerflow.alerting.sinks.pagerduty import PagerDutySink

    pd_sink: PagerDutySink | None = None
    _pd_task: asyncio.Task[None] | None = None
    pd_session: aiohttp.ClientSession | None = None
    if config.alerting.pagerduty_routing_key:
        _pd_connector = aiohttp.TCPConnector(
            ssl=_ssl.create_default_context(),
            limit_per_host=10,
        )
        pd_session = aiohttp.ClientSession(connector=_pd_connector)
        pd_sink = PagerDutySink(config.alerting.pagerduty_routing_key, pd_session)
        _pd_task = asyncio.create_task(pd_sink.run())
        _log.info("PagerDuty sink: routing key configured")

    from seerflow.alerting.sinks.otlp import OtlpSink, masked_url

    otlp_sink: OtlpSink | None = None
    _otlp_task: asyncio.Task[None] | None = None
    if config.alerting.otlp_endpoint:
        otlp_sink = OtlpSink(
            endpoint=config.alerting.otlp_endpoint,
            protocol=config.alerting.otlp_protocol,
            export_interval=config.alerting.otlp_export_interval_seconds,
            tls=config.alerting.otlp_tls,
        )
        _otlp_task = asyncio.create_task(otlp_sink.run())
        _log.info(
            "OTLP sink: %s via %s (interval=%ds)",
            masked_url(config.alerting.otlp_endpoint),
            config.alerting.otlp_protocol,
            config.alerting.otlp_export_interval_seconds,
        )

    handler = make_handler(
        ensemble,
        storage,
        save_interval_ns=save_interval_ns,
        sigma_holder=sigma_holder,
        entity_graph=entity_graph,
        graph_algo_interval=config.detection.graph_algo_interval,
        window_buffer=window_buffer,
        watermark=watermark,
        risk_register=risk_register,
        correlation_holder=correlation_holder,
        alerting_config=config.alerting,
        alert_dispatcher=dispatcher,
        pagerduty_sink=pd_sink,
        otlp_sink=otlp_sink,
        attack_mapper=attack_mapper,
        graph_structural=graph_structural,
        kill_chain_tracker=kill_chain_tracker,
        baseline_store=baseline_store,
        ueba_engine=ueba_engine,
        ueba_alert_cooldown_ns=config.ueba.alert_cooldown_seconds * 1_000_000_000,
        ws_manager=ws_manager,
        ioc_matcher=ioc_matcher,
        ioc_enrichment_counters=ioc_enrichment_counters,
    )
    # Wire the live pipeline metrics provider for /api/v1/stats (S-067 ext).
    # ``taxii_registry`` is supplied so the route can surface per-feed counters
    # whenever ``threat_intel.enabled`` is True; otherwise the registry is
    # empty and the route emits ``taxii=None``.
    from seerflow.api.metrics import build_pipeline_metrics_provider

    api_app.state.pipeline_metrics_provider = build_pipeline_metrics_provider(
        handler,
        ensemble,
        time.monotonic(),
        taxii_registry=taxii_manager.metrics,
        ioc_matcher=ioc_matcher,
        ioc_enrichment_counters=ioc_enrichment_counters,
    )
    # Run pipeline + uvicorn server as sibling tasks (S-217). The first
    # to complete (or fail) wakes the wait so we can drain both cleanly.
    pipeline_task = asyncio.create_task(pipeline.run(handler), name="seerflow.pipeline")

    try:
        done, _pending = await asyncio.wait(
            {pipeline_task, server_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()  # surfaces exceptions raised inside either task
    except KeyboardInterrupt:  # pragma: no cover — handled by signal path
        _log.info("Interrupt received — shutting down")

    # Cancel the rule reloader on shutdown
    reload_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reload_task

    # Cancel the pipeline task if uvicorn died first (or vice versa).
    if not pipeline_task.done():
        pipeline_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pipeline_task
    # Surface any exception the survivor task raised after the wait
    # returned, otherwise it would silently become an "unhandled exception
    # in Task" warning at GC time. ``CancelledError`` is the expected exit
    # for the cancelled survivor, so it is skipped.
    for _peer_task in (pipeline_task, server_task):
        if not _peer_task.done() or _peer_task.cancelled():
            continue
        try:
            _peer_exc = _peer_task.exception()
        except asyncio.CancelledError:  # pragma: no cover — defensive
            continue
        if _peer_exc is not None:
            _log.warning(
                "Background task %s exited with exception",
                _peer_task.get_name(),
                exc_info=_peer_exc,
            )

    try:
        # Flush remaining template metadata.
        # Event flushing is handled by WriteBuffer.close() inside storage.close().
        get_stats = getattr(handler, "get_stats", None)
        if get_stats is not None:
            events, anomalies, template_meta, t0 = get_stats()
            pending_templates = [t for t in template_meta.values() if t.event_count > 0]
            if pending_templates:
                await storage.write_templates(pending_templates)
                _log.info(
                    "Flushed %d template updates to storage",
                    len(pending_templates),
                )
            elapsed = time.time() - t0
            _log.info("--- Session Summary ---")
            _log.info("  Events processed: %d", events)
            _log.info("  Anomalies detected: %d", anomalies)
            _log.info("  Unique templates: %d", len(template_meta))
            _log.info("  Duration: %.1fs", elapsed)
            if elapsed > 0 and events > 0:
                _log.info("  Throughput: %.0f events/sec", events / elapsed)

        try:
            saved = await ensemble.save_all_state(storage)
            if saved > 0:
                _log.info("Final save: %d model states persisted", saved)
        except Exception:
            _log.warning("Final model save failed", exc_info=True)

        if baseline_store is not None:
            try:
                await baseline_store.flush(storage)
                _log.info("UEBA: flushed %d baselines", len(baseline_store))
            except Exception:
                _log.warning("UEBA baseline flush failed", exc_info=True)
    finally:
        if dispatcher is not None:
            await dispatcher.stop()
        if _dispatcher_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await _dispatcher_task
        if pd_sink is not None:
            await pd_sink.stop()
        if _pd_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await _pd_task
        if pd_session is not None:
            await pd_session.close()
        if otlp_sink is not None:
            await otlp_sink.stop()
            if _otlp_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await _otlp_task
            await otlp_sink.close()
        if webhook_session is not None:
            await webhook_session.close()
        # Stop uvicorn so _lifespan can drain WebSocket frames before
        # the storage handle is released. ``server_task`` is created in
        # the new sibling-task layout introduced by S-217. Suppress
        # ``TimeoutError`` as well as ``CancelledError`` so a slow uvicorn
        # shutdown never strands ``storage.close()`` (would leave the
        # SQLite WAL open).
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(server_task, timeout=10)
        # Stop the IoC matcher BEFORE the manager so its debounce loop is
        # cancelled before TAXII consumers exit (no late listener fires after
        # the rebuild loop has stopped). The manager's stop() handles the
        # remainder of the threat-intel teardown sequence (S-068).
        if ioc_matcher is not None:
            await ioc_matcher.stop()
        # Stop TAXII feed manager BEFORE storage.close() so an in-flight
        # ``_persist`` (snapshot + cursor save_state pair) has up to 2 s
        # — see TAXIIFeedManager.stop() — to drain its current write
        # before storage closes. Polls still mid-flight after the grace
        # window are cancelled and their snapshot is dropped; the next
        # poll will refetch from the last-persisted cursor (S-067).
        await taxii_manager.stop()
        await storage.close()
        _log.info("Seerflow stopped")


async def _run(config_path: str | None) -> None:
    """Load config from path and run the pipeline."""
    config = load_config(config_path)
    await _run_with_config(config)
