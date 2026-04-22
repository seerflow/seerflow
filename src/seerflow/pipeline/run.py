"""Pipeline startup and run functions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl as _ssl
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
import aiohttp.web

from seerflow import __version__
from seerflow.config import SeerflowConfig, load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline import build_pipeline
from seerflow.pipeline.handler import make_handler
from seerflow.storage import connect_storage
from seerflow.ueba.store import BaselineStore

if TYPE_CHECKING:
    from seerflow.alerting.router import NotificationRouter
    from seerflow.config import AlertingConfig

_log = logging.getLogger("seerflow")


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


async def _run_with_config(config: SeerflowConfig) -> None:
    """Run the pipeline with a pre-built config."""
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

    ensemble = DetectionEnsemble(config.detection)
    try:
        loaded = await ensemble.load_all_state(storage)
        if loaded > 0:
            _log.info("Restored %d model states from storage", loaded)
    except Exception:
        _log.warning("Failed to restore model state — starting fresh", exc_info=True)

    # UEBA baseline store — feature-flag gated by config.ueba.enabled.
    baseline_store: BaselineStore | None = None
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
        await storage.close()
        sys.exit(1)

    # Startup banner — only list healthy receivers
    receivers = [sid for sid, r in pipeline.manager._receivers.items() if r.is_healthy()]
    _log.info("Receivers: %s", ", ".join(receivers) if receivers else "none")

    # Graceful shutdown via event (Unix only)
    _shutdown_task: asyncio.Task[None] | None = None
    if sys.platform != "win32":  # pragma: no branch
        import signal

        def _request_shutdown() -> None:  # pragma: no cover — called by OS signal only
            nonlocal _shutdown_task
            if _shutdown_task is None:
                _shutdown_task = asyncio.create_task(pipeline.stop())

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_shutdown)

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

    # Start health endpoint server on dashboard_port
    from seerflow.api.health import _STORAGE_KEY, create_health_app

    health_state = {"pipeline": "running", "storage": "connected"}
    health_app = create_health_app(state=health_state)
    health_app[_STORAGE_KEY] = storage
    health_runner = aiohttp.web.AppRunner(health_app)
    await health_runner.setup()
    health_site = aiohttp.web.TCPSite(
        health_runner,
        config.health_bind_address,
        config.dashboard_port,
    )
    await health_site.start()
    _log.info(
        "Health endpoint listening on %s:%d",
        config.health_bind_address,
        config.dashboard_port,
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
    )
    await pipeline.run(handler)

    # Cancel the rule reloader on shutdown
    reload_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reload_task

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
        if otlp_sink is not None:
            await otlp_sink.close()
        if webhook_session is not None:
            await webhook_session.close()
        await health_runner.cleanup()
        await storage.close()
        _log.info("Seerflow stopped")


async def _run(config_path: str | None) -> None:
    """Load config from path and run the pipeline."""
    config = load_config(config_path)
    await _run_with_config(config)
