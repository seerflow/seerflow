"""Entry point for ``python -m seerflow``."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import TYPE_CHECKING

import msgspec.structs

from seerflow import __version__
from seerflow.cli import parse_args
from seerflow.config import ReceiverConfig, SeerflowConfig, load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.pipeline import build_pipeline

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.receivers.base import RawEvent
    from seerflow.storage.sqlite import SqliteBackend

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
    loaded = await ensemble.load_all_state(storage)
    if loaded > 0:
        _log.info("Restored %d model states from storage", loaded)
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

    _log.info("Pipeline running — Ctrl+C to stop")
    save_interval_ns = config.detection.model_save_interval_seconds * 1_000_000_000
    handler = _make_handler(ensemble, storage, save_interval_ns=save_interval_ns)
    await pipeline.run(handler)

    # Flush remaining template metadata.
    # Event flushing is handled by WriteBuffer.close() inside storage.close() below.
    get_stats = getattr(handler, "get_stats", None)
    if get_stats is not None:
        events, anomalies, template_meta, t0 = get_stats()
        pending_templates = [t for t in template_meta.values() if t.event_count > 0]
        if pending_templates:
            await storage.write_templates(pending_templates)
            _log.info("Flushed %d template updates to storage", len(pending_templates))
        elapsed = time.time() - t0
        _log.info("--- Session Summary ---")
        _log.info("  Events processed: %d", events)
        _log.info("  Anomalies detected: %d", anomalies)
        _log.info("  Unique templates: %d", len(template_meta))
        _log.info("  Duration: %.1fs", elapsed)
        if elapsed > 0 and events > 0:
            _log.info("  Throughput: %.0f events/sec", events / elapsed)

    saved = await ensemble.save_all_state(storage)
    if saved > 0:
        _log.info("Final save: %d model states persisted", saved)

    await storage.close()
    _log.info("Seerflow stopped")


def _make_handler(
    ensemble: DetectionEnsemble,
    storage: SqliteBackend,
    save_interval_ns: int = 300_000_000_000,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection and persists events."""
    from seerflow.models.alert import create_ml_alert
    from seerflow.parsing import EventNormalizer
    from seerflow.storage.sqlite import TemplateInfo

    normalizer = EventNormalizer()
    event_count = 0
    anomaly_count = 0
    template_meta: dict[int, TemplateInfo] = {}
    start_time = time.time()
    last_save_ns = time.time_ns()

    async def handler(event: RawEvent) -> None:
        seerflow_event = normalizer.normalize(event)

        # Derive entity_refs for HST entity_count + storage compatibility
        entity_refs = (
            seerflow_event.related_ips
            + seerflow_event.related_users
            + seerflow_event.related_hosts
        )
        if entity_refs:
            seerflow_event = msgspec.structs.replace(
                seerflow_event,
                entity_refs=entity_refs,
            )

        # Track template metadata
        if seerflow_event.template_id != -1:
            if seerflow_event.template_id not in template_meta:
                _log.info(
                    "New template discovered: [%d] %s",
                    seerflow_event.template_id,
                    seerflow_event.template_str[:120],
                )
                template_meta[seerflow_event.template_id] = TemplateInfo(
                    template_id=seerflow_event.template_id,
                    template_str=seerflow_event.template_str,
                    first_seen_ns=event.received_ns,
                    last_seen_ns=event.received_ns,
                    event_count=1,
                    example_message=seerflow_event.message[:500],
                )
            else:
                existing = template_meta[seerflow_event.template_id]
                template_meta[seerflow_event.template_id] = TemplateInfo(
                    template_id=seerflow_event.template_id,
                    template_str=seerflow_event.template_str,
                    first_seen_ns=existing.first_seen_ns,
                    last_seen_ns=event.received_ns,
                    event_count=existing.event_count + 1,
                    example_message=existing.example_message,
                )

        # Persist to storage (WriteBuffer handles batching + 100ms timer flush)
        await storage.write_events([seerflow_event])

        result = ensemble.process_event(seerflow_event)
        nonlocal event_count, anomaly_count, last_save_ns
        event_count += 1

        # Flush template metadata every 10 events
        if event_count % 10 == 0 and template_meta:
            pending = list(template_meta.values())
            await storage.write_templates(pending)
            # Reset counts only after successful write
            for tid in template_meta:
                t = template_meta[tid]
                template_meta[tid] = TemplateInfo(
                    template_id=t.template_id,
                    template_str=t.template_str,
                    first_seen_ns=t.first_seen_ns,
                    last_seen_ns=t.last_seen_ns,
                    event_count=0,
                    example_message=t.example_message,
                )
        if result.is_anomaly:
            anomaly_count += 1
        _log.debug(
            "event tid=%d entities=%d score=%.4f thresh=%.4f src=%s",
            seerflow_event.template_id,
            len(entity_refs),
            result.score,
            result.upper_threshold,
            event.source_type,
        )
        if result.is_anomaly:  # pragma: no cover — tested in test_detection_ensemble
            _log.warning(
                "ANOMALY [%s] score=%.3f threshold=%.3f dir=%s",
                result.source_type,
                result.score,
                result.upper_threshold,
                result.anomaly_direction,
            )
            _log.warning(
                "  template: [%d] %s",
                seerflow_event.template_id,
                seerflow_event.template_str[:120],
            )
            _log.warning(
                "  message:  %s",
                seerflow_event.message[:200],
            )
            if entity_refs:
                _log.warning(
                    "  entities: %s",
                    ", ".join(entity_refs[:10]),
                )
            alert = create_ml_alert(seerflow_event, result)
            await storage.write_alert(alert)

        # Periodic model state save
        if event_count % 100 == 0 and event_count > 0:
            now_ns = time.time_ns()
            if now_ns - last_save_ns >= save_interval_ns:
                try:
                    saved = await ensemble.save_all_state(storage)
                    _log.info("Periodic save: %d model states", saved)
                    last_save_ns = now_ns
                except Exception:
                    _log.warning(
                        "Periodic model save failed — will retry",
                        exc_info=True,
                    )

    handler.get_stats = lambda: (event_count, anomaly_count, template_meta, start_time)  # type: ignore[attr-defined]
    return handler


async def _run(config_path: str | None) -> None:
    """Load config from path and run the pipeline."""
    config = load_config(config_path)
    await _run_with_config(config)


def _build_tail_config(paths: list[str], config_path: str | None = None) -> SeerflowConfig:
    """Build a SeerflowConfig for tail mode (file receivers only)."""
    base = load_config(config_path)
    tail_receivers = ReceiverConfig(
        syslog_enabled=False,
        otlp_grpc_enabled=False,
        otlp_http_enabled=False,
        webhook_enabled=False,
        file_paths=tuple(paths),
    )
    return SeerflowConfig(
        receivers=tail_receivers,
        storage=base.storage,
        detection=base.detection,
        alerting=base.alerting,
        llm=base.llm,
        log_level=base.log_level,
    )


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        if args.command == "tail":
            tail_config = _build_tail_config(args.paths, config_path=args.config)
            asyncio.run(_run_with_config(tail_config))
        elif args.command == "query":
            from seerflow.query import run_query

            asyncio.run(run_query(args))
        else:
            asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
