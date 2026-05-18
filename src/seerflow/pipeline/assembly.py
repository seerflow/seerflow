"""Full-stack detection handler assembly (S-302, FR-069).

A single shared pure async factory that builds the exact engine wiring
``pipeline/run.py::_run_with_config`` feeds into ``make_handler`` today —
NO receivers (``build_pipeline``), NO FastAPI/uvicorn, NO LLM (API-only).

This makes live ``seerflow start`` ≡ ``seerflow analyze`` ≡ the LANL
benchmark wire detection identically by construction (NFR-013/017). The
behaviour-preserving refactor of ``_run_with_config`` to consume this
factory is S-304, guarded by ``tests/unit/test_pipeline_run_characterization.py``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl as _ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline.handler import make_handler
from seerflow.threat_intel import IoCMatcher, TAXIIFeedManager
from seerflow.threat_intel.enricher import _IoCEnrichmentCounters

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.config import SeerflowConfig
    from seerflow.receivers.base import RawEvent
    from seerflow.storage.factory import StorageBackend
    from seerflow.ueba.engine import UEBAEngine
    from seerflow.ueba.store import BaselineStore

_log = logging.getLogger("seerflow")


@dataclass(frozen=True, slots=True)
class AssembledHandler:
    """Result of :func:`assemble_handler`.

    - ``handler``     — the ``make_handler(...)`` event closure.
    - ``lifecycle``   — background ``asyncio.Task``s the factory started
                         (rule reloader, dispatcher/sink run loops).
    - ``teardown``    — idempotent async stop-and-await for owned resources;
                         does NOT close ``storage`` (caller-owned) or touch
                         uvicorn (none built).
    - ``capture_sink`` — passthrough seam for S-303 (analyze/benchmark);
                         accepted but not yet wired into ``make_handler``.
    """

    handler: Callable[[RawEvent], Awaitable[None]]
    lifecycle: tuple[asyncio.Task[Any], ...]
    teardown: Callable[[], Awaitable[None]]
    capture_sink: object | None


async def assemble_handler(
    config: SeerflowConfig,
    storage: StorageBackend,
    *,
    capture_sink: object | None = None,
) -> AssembledHandler:
    """Build the full-stack ``make_handler(...)`` wiring (no receivers/API).

    Reproduces ``run.py::_run_with_config`` lines 440–901 minus storage
    connect, receivers, signal handlers, FastAPI/uvicorn, LLM/services and
    the metrics provider. Same construction, same order — the S-301
    characterization test pins the live side; ``test_pipeline_assembly``
    pins this side (``ws_manager`` is ``None`` here by design).
    """
    # --- TAXII feed manager + IoC matcher (run.py:440-471) ---
    taxii_manager = TAXIIFeedManager(config=config.threat_intel, model_store=storage)
    ioc_matcher: IoCMatcher | None = None
    if config.threat_intel.matcher.enabled:
        ioc_matcher = IoCMatcher(config=config.threat_intel, model_store=storage)
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

    # --- DetectionEnsemble + state restore (run.py:473-479) ---
    ensemble = DetectionEnsemble(config.detection)
    try:
        loaded = await ensemble.load_all_state(storage)
        if loaded > 0:
            _log.info("Restored %d model states from storage", loaded)
    except Exception:
        _log.warning("Failed to restore model state — starting fresh", exc_info=True)

    # --- UEBA baseline store + engine, flag-gated (run.py:482-503) ---
    baseline_store: BaselineStore | None = None
    ueba_engine: UEBAEngine | None = None
    if config.ueba.enabled:
        from seerflow.ueba.baseline import UEBAParams
        from seerflow.ueba.engine import UEBAEngine
        from seerflow.ueba.store import BaselineStore

        ueba_params = UEBAParams(
            alpha=config.ueba.ema_alpha,
            source_ip_cap=config.ueba.source_ip_cap,
            template_top_k=config.ueba.template_top_k,
            warmup_days=config.ueba.warmup_days,
            warmup_min_events=config.ueba.warmup_min_events,
        )
        baseline_store = BaselineStore(
            params=ueba_params, max_entities=config.ueba.max_entities
        )
        try:
            restored = await baseline_store.restore(storage)
            _log.info("UEBA: restored %d baselines", restored)
        except Exception:
            _log.warning("UEBA baseline restore failed", exc_info=True)
        ueba_engine = UEBAEngine(config=config.ueba)

    # --- ATT&CK mapper (run.py:505-518) ---
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

    # --- Sigma engine + holder (run.py:547-559, 638-640) ---
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

    # --- Entity graph + edges (run.py:561-571) ---
    from seerflow.graph.entity_graph import EntityGraph

    entity_graph = EntityGraph()
    try:
        edge_rows = await storage.load_edges()
        entity_graph.load(edge_rows)
        _log.info("Graph: loaded %d edges", len(edge_rows))
    except Exception:
        _log.warning("Graph edge loading failed — starting with empty graph", exc_info=True)
    storage.set_entity_graph(entity_graph)

    # --- Graph-structural evaluator (run.py:573-577) ---
    from seerflow.correlation.graph_structural import GraphStructuralEvaluator

    graph_structural = GraphStructuralEvaluator(config.detection.graph_structural, entity_graph)
    _log.info("Graph-structural evaluator: enabled")

    # --- Kill-chain tracker, flag-gated (run.py:579-589) ---
    from seerflow.correlation.kill_chain import KillChainTracker

    kill_chain_tracker: KillChainTracker | None = None
    if config.detection.kill_chain.enabled:
        kill_chain_tracker = KillChainTracker(config.detection.kill_chain)
        _log.info(
            "Kill-chain tracker: threshold=%d, window=%ds",
            config.detection.kill_chain.tactic_threshold,
            config.detection.kill_chain.window_seconds,
        )

    # --- Window buffer / watermark / risk register (run.py:591-614) ---
    from seerflow.correlation.watermark import Watermark
    from seerflow.correlation.window import EntityWindowBuffer

    window_buffer = EntityWindowBuffer(
        window_ns=config.correlation.window_duration_seconds * 1_000_000_000,
        max_events=config.correlation.max_events_per_entity,
        max_entities=config.correlation.max_entities,
    )
    watermark = Watermark(
        tolerance_ns=config.correlation.late_tolerance_seconds * 1_000_000_000,
    )
    from seerflow.correlation.risk import RiskRegister

    risk_register = RiskRegister(
        half_life_ns=config.detection.risk_half_life_hours * 3600 * 1_000_000_000,
        threshold=config.detection.risk_threshold,
        max_entities=config.detection.risk_max_entities,
    )

    # --- Correlation rules + engine + holder + reloader (run.py:616-653) ---
    from seerflow.correlation.bundled import get_bundled_rule_dir
    from seerflow.correlation.engine import CorrelationEngine
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.reloader import RuleReloader
    from seerflow.correlation.rule_loader import load_correlation_rules

    bundled_dir = str(get_bundled_rule_dir())
    rule_dirs = (bundled_dir, *config.correlation.rule_dirs)
    correlation_rules = load_correlation_rules(rule_dirs)
    _log.info(
        "Correlation: loaded %d rules from %d dirs",
        len(correlation_rules),
        len(rule_dirs),
    )
    correlation_engine = CorrelationEngine(rules=correlation_rules, window=window_buffer)
    _log.info("Correlation engine: %d rules loaded", len(correlation_rules))

    sigma_holder = EngineHolder(engine=sigma_engine)
    correlation_holder: EngineHolder[CorrelationEngine | None] = EngineHolder(
        engine=correlation_engine
    )
    reloader = RuleReloader(
        correlation_holder=correlation_holder,
        correlation_dirs=[bundled_dir, *config.correlation.rule_dirs],
        window_buffer=window_buffer,
    )
    reload_task = asyncio.create_task(reloader.watch())

    # --- Per-stage latency tracker (run.py:740) ---
    from seerflow.api.latency import StageLatencyTracker

    stage_latency_tracker = StageLatencyTracker()

    # --- save interval (run.py:802) ---
    save_interval_ns = config.detection.model_save_interval_seconds * 1_000_000_000

    # --- Alert dispatcher + channel session/router (run.py:804-837) ---
    import aiohttp

    from seerflow.alerting.dispatcher import (
        AlertDispatcher,
        build_webhook_delivery_targets,
    )
    from seerflow.pipeline.run import _build_channel_session_and_router

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

    # --- PagerDuty sink (run.py:839-852) ---
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

    # --- OTLP sink (run.py:854-874) ---
    from seerflow.alerting.sinks.otlp import OtlpSink, masked_url

    otlp_sink: OtlpSink | None = None
    _otlp_task: asyncio.Task[None] | None = None
    if config.alerting.otlp_endpoint:
        otlp_sink = OtlpSink(
            endpoint=config.alerting.otlp_endpoint,
            protocol=config.alerting.otlp_protocol,
            export_interval=config.alerting.otlp_export_interval_seconds,
            tls=config.alerting.otlp_tls,
            tls_ca_file=config.alerting.otlp_tls_ca_file,
            mtls_cert_file=config.alerting.otlp_mtls_cert_file,
            mtls_key_file=config.alerting.otlp_mtls_key_file,
        )
        _otlp_task = asyncio.create_task(otlp_sink.run())
        _log.info(
            "OTLP sink: %s via %s (interval=%ds)",
            masked_url(config.alerting.otlp_endpoint),
            config.alerting.otlp_protocol,
            config.alerting.otlp_export_interval_seconds,
        )

    # --- Wired make_handler — IDENTICAL 25 args, ws_manager=None (run.py:876-901) ---
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
        ws_manager=None,
        ioc_matcher=ioc_matcher,
        ioc_enrichment_counters=ioc_enrichment_counters,
        latency_tracker=stage_latency_tracker,
    )

    lifecycle: list[asyncio.Task[Any]] = [reload_task]
    if _dispatcher_task is not None:
        lifecycle.append(_dispatcher_task)
    if _pd_task is not None:
        lifecycle.append(_pd_task)
    if _otlp_task is not None:
        lifecycle.append(_otlp_task)

    _torn_down = False

    async def _teardown() -> None:
        nonlocal _torn_down
        if _torn_down:
            return
        _torn_down = True

        reload_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reload_task
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
        if ioc_matcher is not None:
            await ioc_matcher.stop()
        await taxii_manager.stop()

    return AssembledHandler(
        handler=handler,
        lifecycle=tuple(lifecycle),
        teardown=_teardown,
        capture_sink=capture_sink,
    )
