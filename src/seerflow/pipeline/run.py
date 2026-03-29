"""Pipeline startup and run functions."""

from __future__ import annotations

import asyncio
import logging
import sys
import time

from seerflow import __version__
from seerflow.config import SeerflowConfig, load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline import build_pipeline
from seerflow.pipeline.handler import _make_handler

_log = logging.getLogger("seerflow")


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
    from pathlib import Path

    from seerflow.storage.sqlite import SqliteBackend

    data_dir = Path(config.storage.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    storage = await SqliteBackend.connect(config.storage)
    _log.info("Storage: %s", config.storage.sqlite_path)

    ensemble = DetectionEnsemble(config.detection)
    try:
        loaded = await ensemble.load_all_state(storage)
        if loaded > 0:
            _log.info("Restored %d model states from storage", loaded)
    except Exception:
        _log.warning("Failed to restore model state — starting fresh", exc_info=True)
    pipeline = await build_pipeline(config)

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

    # Load Sigma rules
    from seerflow.sigma.engine import SigmaEngine

    sigma_engine = SigmaEngine()
    sigma_engine.load_bundled()
    if config.detection.sigma_rules_dirs:
        sigma_engine.load_custom(list(config.detection.sigma_rules_dirs))
    _log.info("Sigma: %d rules loaded", sigma_engine.rule_count)

    _log.info("Pipeline running — Ctrl+C to stop")
    save_interval_ns = config.detection.model_save_interval_seconds * 1_000_000_000
    handler = _make_handler(
        ensemble, storage, save_interval_ns=save_interval_ns, sigma_engine=sigma_engine
    )
    await pipeline.run(handler)

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
    finally:
        await storage.close()
        _log.info("Seerflow stopped")


async def _run(config_path: str | None) -> None:
    """Load config from path and run the pipeline."""
    config = load_config(config_path)
    await _run_with_config(config)
