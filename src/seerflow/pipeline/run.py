"""Pipeline startup and run functions.

Shutdown contract (S-081, NFR-008)
----------------------------------

Seerflow exits in three ordered phases:

1. **Signal phase** — ``_install_shutdown_handlers`` registers SIGINT/SIGTERM.
   First signal flips ``uvicorn.Server.should_exit`` and schedules
   ``pipeline.stop()``; a second signal escalates to ``force_exit``.
2. **Cooperative drain phase** — ``_run_shutdown_sequence`` invokes
   ``_persist_session_state`` under ``asyncio.wait_for`` with
   ``SeerflowConfig.shutdown_timeout_s`` (default 30 s, matches kubelet
   ``terminationGracePeriodSeconds``). The drain persists, in order:
   pending template metadata, ML ensemble state, UEBA baselines, and
   Drain3 template state. Each step is best-effort — failures are logged
   at WARNING and the next step still runs.
3. **Resource teardown phase** — the ``finally`` block in
   ``_run_with_config`` stops dispatchers, sinks, IoC matcher, TAXII
   manager, then closes uvicorn and storage. ``storage.close()`` runs
   even on drain timeout so the SQLite WAL is always allowed to flush.

Operators can grep ``Seerflow shutdown sequence (starting|completed)`` to
confirm a clean exit, or ``Shutdown timeout exceeded`` to identify
forced shutdowns.
"""

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
from seerflow.api.anomaly_timeline import AnomalyTimelineRing
from seerflow.api.app import build_ws_manager, create_api_app
from seerflow.api.latency import StageLatencyTracker
from seerflow.config import SeerflowConfig, load_config
from seerflow.pipeline import build_pipeline
from seerflow.pipeline.assembly import assemble_handler
from seerflow.storage import connect_storage
from seerflow.web import DEFAULT_DIST

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import Protocol

    from fastapi import FastAPI

    from seerflow.alerting.router import NotificationRouter
    from seerflow.api.ws import ConnectionManager
    from seerflow.config import AlertingConfig
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.storage.factory import StorageBackend
    from seerflow.ueba.store import BaselineStore

    class _StoppablePipeline(Protocol):
        """Subset of the pipeline contract the shutdown closure needs."""

        async def stop(self) -> None: ...

    class _ExitableServer(Protocol):
        """Subset of ``uvicorn.Server`` the shutdown closure needs."""

        should_exit: bool
        force_exit: bool


_log = logging.getLogger("seerflow")


def _derive_llm_health(backend: object | None, configured_backend: str) -> str:
    """Three-state ``health_state["llm"]`` value (S-070).

    - ``ready``    → backend instance constructed
    - ``disabled`` → operator did not configure a backend (intentional)
    - ``degraded`` → operator configured a backend that could not be loaded
    """
    if backend is not None:
        return "ready"
    if not configured_backend:
        return "disabled"
    return "degraded"


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


async def _persist_session_state(
    handler: object | None,
    storage: StorageBackend,
    ensemble: DetectionEnsemble,
    baseline_store: BaselineStore | None,
) -> None:
    """Run the best-effort drain steps that must complete before storage.close().

    S-081 — extracted from ``_run_with_config``. Each step is wrapped in a
    try/except so a failure in one stage does not abort the others. Order:

    1. Flush pending template metadata accumulated by the handler (S-015).
    2. Persist ML model state (S-026).
    3. Flush UEBA baselines (S-064 / S-097).
    4. Persist Drain3 template state (S-015 / S-081 new wiring).

    ``handler is None`` is tolerated so the helper can be called from the
    startup-failure path before ``make_handler`` returns.
    """
    if handler is not None:
        try:
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
        except Exception:
            _log.warning("Session summary / template flush failed", exc_info=True)

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

    # S-081: persist Drain3 template state so the next boot warms up with the
    # full vocabulary instead of rebuilding from scratch. Wired in via
    # ``EventNormalizer.parser`` (exposed on the handler closure as
    # ``handler.get_normalizer``). Best-effort — Drain3 rebuilds on next boot.
    # WAL safety on cancellation: a wait_for-driven timeout cancels the
    # current await inside ``save_state``; ``CancelledError`` is a
    # ``BaseException`` so it bypasses the local ``except Exception`` rollback,
    # but the outer ``_run_with_config`` ``finally`` block still calls
    # ``storage.close()`` which invokes ``aiosqlite.Connection.close()`` →
    # ``sqlite3.Connection.close()``, and CPython's stdlib sqlite3 module
    # auto-rolls-back any open transaction on connection close. Net: the
    # WAL never persists a half-written drain3 blob.
    if handler is not None:
        try:
            get_normalizer = getattr(handler, "get_normalizer", None)
            if get_normalizer is not None:
                from seerflow.parsing.drain_persistence import save_drain_state

                normalizer = get_normalizer()
                await save_drain_state(normalizer.parser, storage)
        except Exception:
            _log.warning("Drain3 state save failed", exc_info=True)


async def _run_shutdown_sequence(
    *,
    handler: object | None,
    storage: StorageBackend,
    ensemble: DetectionEnsemble,
    baseline_store: BaselineStore | None,
    timeout: float,
) -> None:
    """Bounded wrapper around ``_persist_session_state`` (S-081 / NFR-008).

    Emits structured INFO log lines bracketing the drain phase and a WARNING on
    timeout. Returns normally even on timeout so the caller's ``finally`` block
    can still run resource teardown (uvicorn, sinks, storage). Storage close
    must NOT live inside this wait — the SQLite WAL must always be allowed to
    finish writing.
    """
    started = time.monotonic()
    _log.info("Seerflow shutdown sequence starting (timeout=%.1fs)", timeout)
    try:
        await asyncio.wait_for(
            _persist_session_state(handler, storage, ensemble, baseline_store),
            timeout=timeout,
        )
    except TimeoutError:
        elapsed = time.monotonic() - started
        _log.warning(
            "Shutdown timeout exceeded — forcing exit (took %.2fs, bound=%.1fs)",
            elapsed,
            timeout,
        )
        return
    elapsed = time.monotonic() - started
    _log.info("Seerflow shutdown sequence completed (took %.2fs)", elapsed)


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

    # S-304: build the detection handler via the shared factory
    # (``pipeline.assembly.assemble_handler``). This is the SAME wiring
    # ``seerflow analyze`` (S-303) and the LANL benchmark (S-305) consume,
    # so live ≡ analyze ≡ benchmark detection is identical by construction
    # (FR-069 / NFR-013/017). The factory owns every engine + the alert
    # sinks + the rule reloader; the live caller keeps only the live-only
    # concerns (receivers, signal handlers, FastAPI/uvicorn, LLM services,
    # metrics provider, the S-081 shutdown drain).
    #
    # ``ws_manager`` is the one intentional divergence from the factory
    # default of ``None``: the live pipeline must broadcast WebSocket
    # frames, so the ``ConnectionManager`` is built ONCE here (identical
    # CSWSH / queue / tick wiring as the in-app default via
    # ``build_ws_manager``) and injected into BOTH the factory (so the
    # handler closure broadcasts) and ``create_api_app`` (so the
    # ``/api/v1/ws`` route shares the same fan-out). The
    # ``AnomalyTimelineRing`` is built here too and reused so the
    # ``/api/v1/anomaly`` route reads the ring the manager records into.
    # Validate receivers FIRST (fail fast, S-141). The original
    # ``_run_with_config`` called ``build_pipeline`` before the
    # arithmetic-heavy engine assembly so a receiver bind failure exits
    # cleanly before any engine is constructed; preserve that ordering —
    # nothing is assembled yet on the failure path, so only storage needs
    # closing (no factory teardown required).
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

    timeline_ring = AnomalyTimelineRing()
    ws_manager: ConnectionManager = build_ws_manager(storage, config, timeline_ring)

    assembled = await assemble_handler(config, storage, ws_manager=ws_manager)
    engines = assembled.engines
    handler = assembled.handler

    # LLM backend (S-070). Built once at boot; ``None`` on graceful absence
    # (no backend configured, optional dep missing, model file missing) so
    # downstream consumers (S-071 alert explanation, S-072 NL hunt) can
    # null-check before calling ``complete(...)``.
    from seerflow.llm import LLMBackend, build_llm_backend

    llm_backend: LLMBackend | None = build_llm_backend(config.llm)

    # Startup banner — only list healthy receivers
    receivers = [sid for sid, r in pipeline.manager._receivers.items() if r.is_healthy()]
    _log.info("Receivers: %s", ", ".join(receivers) if receivers else "none")

    # Graceful shutdown — register SIGINT/SIGTERM handlers that will flip uvicorn's
    # ``should_exit`` flag and stop the pipeline once the server is wired in below.
    shutdown_ctx = _install_shutdown_handlers(asyncio.get_running_loop(), pipeline)

    # Mount FastAPI dashboard + REST + WebSocket on dashboard_port via
    # uvicorn (S-217). The legacy aiohttp ``health_app`` was deleted —
    # the FastAPI ``/api/v1/health`` route mirrors its contract.
    #
    # The introspection objects (sigma engine, correlation rules, ensemble,
    # baseline store, UEBA engine) are the SAME instances the factory built
    # — passed straight through from ``assembled.engines`` so the API
    # observes exactly what the live pipeline runs (no duplicate
    # construction; S-304 AC1).

    # ``llm`` health (S-070): three-state surface
    #   ready    → backend constructed
    #   disabled → operator did not configure a backend
    #   degraded → operator configured a backend but it could not be loaded
    health_state: dict[str, str] = {
        "pipeline": "running",
        "storage": "connected",
        "llm": _derive_llm_health(llm_backend, config.llm.backend),
    }
    # Alert explanation service (S-071). Constructed only when the LLM
    # backend loaded successfully; the routes return 503 with the
    # ``health_state["llm"]`` status when ``explanation_service is None``.
    from seerflow.llm.explanation import (
        AlertExplanationService,
        ExplanationCache,
    )

    explanation_service: AlertExplanationService | None = None
    if llm_backend is not None:
        explanation_cache = ExplanationCache(
            max_entries=config.llm.explanation_cache_size,
            ttl_seconds=config.llm.explanation_cache_ttl_s,
        )
        explanation_service = AlertExplanationService(
            backend=llm_backend,
            cache=explanation_cache,
            cfg=config.llm,
            alert_store=storage,
            log_store=storage,
            baseline_store=engines.baseline_store,
        )

    # Natural language hunt service (S-072). Same construction pattern as
    # the explanation service: only built when the LLM backend is ready;
    # the route returns 503 otherwise.
    from seerflow.llm.hunt import HuntCache, NaturalLanguageHuntService

    hunt_service: NaturalLanguageHuntService | None = None
    if llm_backend is not None:
        hunt_cache = HuntCache(
            max_entries=config.llm.hunt_cache_size,
            ttl_seconds=config.llm.hunt_cache_ttl_s,
        )
        hunt_service = NaturalLanguageHuntService(
            backend=llm_backend,
            cache=hunt_cache,
            cfg=config.llm,
            log_store=storage,
        )

    # Sigma rule-suggestion service (S-100, FR-066). Same lifecycle as the
    # explanation + hunt services: only constructed when the LLM backend
    # is ready; the three routes return 503 with the ``health_state["llm"]``
    # status otherwise.
    from seerflow.llm.rule_suggestion import RuleSuggestionCache, RuleSuggestionService

    rule_suggestion_service: RuleSuggestionService | None = None
    if llm_backend is not None:
        rule_suggestion_cache = RuleSuggestionCache(
            max_entries=config.llm.rule_suggestion_cache_size,
            ttl_seconds=config.llm.rule_suggestion_cache_ttl_s,
        )
        rule_suggestion_service = RuleSuggestionService(
            backend=llm_backend,
            cache=rule_suggestion_cache,
            cfg=config.llm,
            alert_store=storage,
            log_store=storage,
        )

    # S-080: shared per-stage latency tracker. Owned by the runner so the
    # pipeline handler and the FastAPI ``/api/v1/health`` route observe the
    # same rolling reservoir. Stays an in-memory ring buffer; no external
    # dependency, no persistence, no extra CPU on the no-op path.
    stage_latency_tracker = StageLatencyTracker()

    api_app = make_api_app(
        log_store=storage,
        alert_store=storage,
        entity_store=storage,
        config=config,
        ws_manager=ws_manager,
        sigma_engine=engines.sigma_engine,
        correlation_rules=engines.correlation_rules,
        baseline_store=engines.baseline_store,
        ueba_engine=engines.ueba_engine,
        sigma_state_store=storage,
        health_state=health_state,
        ensemble=engines.ensemble,
        explanation_service=explanation_service,
        hunt_service=hunt_service,
        rule_suggestion_service=rule_suggestion_service,
        stage_latency_tracker=stage_latency_tracker,
    )
    # Reuse the timeline ring the injected ws_manager records into so the
    # ``/api/v1/anomaly`` route reads the same ring (``create_api_app``
    # builds a fresh ring by default; the injected manager already holds
    # ``timeline_ring`` so overwrite to keep them the same instance).
    api_app.state.anomaly_timeline_ring = timeline_ring
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

    # ``handler`` + every alert sink + the rule reloader were already built
    # by ``assemble_handler`` above (S-304). The metrics provider is a
    # live-only concern (the offline ``analyze``/benchmark consumers do not
    # expose ``/api/v1/stats``) so it stays here, sourced from the factory's
    # introspection bundle so it observes exactly what the pipeline runs.
    from seerflow.api.metrics import build_pipeline_metrics_provider

    api_app.state.pipeline_metrics_provider = build_pipeline_metrics_provider(
        handler,
        engines.ensemble,
        time.monotonic(),
        taxii_registry=engines.taxii_manager.metrics,
        ioc_matcher=engines.ioc_matcher,
        ioc_enrichment_counters=engines.ioc_enrichment_counters,
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
        # S-081: bounded cooperative drain — Drain3 templates + ML state + UEBA
        # baselines persist within ``config.shutdown_timeout_s`` (default 30 s,
        # matches kubelet ``terminationGracePeriodSeconds``). On timeout the
        # helper returns normally so the ``finally`` block still tears down
        # the assembled resources + uvicorn + storage; the SQLite WAL is
        # never cancelled mid-write. ``ensemble``/``baseline_store`` are the
        # SAME instances the factory built (S-304) — sourced from the
        # introspection bundle so the final ML/UEBA save persists the live
        # pipeline's state.
        await _run_shutdown_sequence(
            handler=handler,
            storage=storage,
            ensemble=engines.ensemble,
            baseline_store=engines.baseline_store,
            timeout=config.shutdown_timeout_s,
        )
    finally:
        # ``assembled.teardown()`` is idempotent and owns the full
        # threat-intel + sink + reloader teardown: it cancels + awaits the
        # rule reloader / dispatcher / PagerDuty / OTLP tasks (with
        # ``CancelledError`` suppression), closes the webhook + PagerDuty
        # sessions, then stops the IoC matcher BEFORE the TAXII manager
        # (documented S-068 order). Do NOT double-cancel any of these.
        await assembled.teardown()
        # Stop uvicorn so _lifespan can drain WebSocket frames before
        # the storage handle is released. ``server_task`` is created in
        # the sibling-task layout introduced by S-217. Suppress
        # ``TimeoutError`` as well as ``CancelledError`` so a slow uvicorn
        # shutdown never strands ``storage.close()`` (would leave the
        # SQLite WAL open).
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(server_task, timeout=10)
        # Storage is caller-owned (the factory teardown deliberately does
        # NOT close it) so close it last, even on drain timeout, so the
        # SQLite WAL is always allowed to flush.
        await storage.close()
        _log.info("Seerflow stopped")


async def _run(config_path: str | None) -> None:
    """Load config from path and run the pipeline."""
    config = load_config(config_path)
    await _run_with_config(config)
