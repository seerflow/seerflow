"""Entry point for ``python -m seerflow``."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from typing import TYPE_CHECKING

from seerflow import __version__
from seerflow.cli import parse_args
from seerflow.config import load_config
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent
from seerflow.pipeline import build_pipeline

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.receivers.base import RawEvent
    from seerflow.storage.sqlite import SqliteBackend

_log = logging.getLogger("seerflow")


async def _run(config_path: str | None) -> None:
    # Bootstrap logging early so load_config errors surface
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    config = load_config(config_path)

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
    pipeline = await build_pipeline(config)

    # Startup banner — only list healthy receivers
    receivers = [sid for sid, r in pipeline.manager._receivers.items() if r.is_healthy()]
    _log.info("Receivers: %s", ", ".join(receivers) if receivers else "none")

    # Graceful shutdown via event (Unix only)
    _shutdown_task: asyncio.Task[None] | None = None
    if sys.platform != "win32":
        import signal

        def _request_shutdown() -> None:  # pragma: no cover — called by OS signal only
            nonlocal _shutdown_task
            if _shutdown_task is None:
                _shutdown_task = asyncio.create_task(pipeline.stop())

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_shutdown)

    _log.info("Pipeline running — Ctrl+C to stop")
    handler = _make_handler(ensemble, storage)
    await pipeline.run(handler)

    # Flush remaining batch
    if hasattr(handler, "stats"):
        s = handler.stats  # type: ignore[union-attr]
        elapsed = time.time() - s["start_time"]
        _log.info("--- Session Summary ---")
        _log.info("  Events processed: %d", s["events"])
        _log.info("  Anomalies detected: %d", s["anomalies"])
        _log.info("  Unique templates: %d", len(s["templates"]))
        _log.info("  Duration: %.1fs", elapsed)
        if elapsed > 0 and s["events"] > 0:
            _log.info("  Throughput: %.0f events/sec", s["events"] / elapsed)

    await storage.close()
    _log.info("Seerflow stopped")


def _make_handler(
    ensemble: DetectionEnsemble,
    storage: SqliteBackend,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection and persists events."""
    from seerflow.parsing import DrainParser, EntityExtractor

    drain = DrainParser()
    extractor = EntityExtractor()
    batch: list[SeerflowEvent] = []
    batch_size = 50
    stats = {"events": 0, "anomalies": 0, "templates": set(), "start_time": time.time()}

    async def handler(event: RawEvent) -> None:
        message = event.data.decode("utf-8", errors="replace")[:32768]

        # Parse template via Drain3
        template_id, template_str, template_params = drain.parse(message)

        # Extract entities
        entities = extractor.extract(message)
        entity_refs = tuple(v for vals in entities.values() for v in vals)

        seerflow_event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=event.received_ns,
            observed_ns=time.time_ns(),
            message=message,
            source_type=event.source_type,
            source_id=event.source_id,
            template_id=template_id,
            template_str=template_str,
            template_params=template_params,
            entity_refs=entity_refs,
        )

        # Persist to storage
        batch.append(seerflow_event)
        if len(batch) >= batch_size:
            await storage.write_events(list(batch))
            batch.clear()

        result = ensemble.process_event(seerflow_event)
        stats["events"] += 1
        stats["templates"].add(template_id)
        if result.is_anomaly:
            stats["anomalies"] += 1
        _log.debug(
            "event tid=%d entities=%d score=%.4f thresh=%.4f src=%s",
            template_id,
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
                template_id,
                template_str[:120],
            )
            _log.warning(
                "  message:  %s",
                message[:200],
            )
            if entity_refs:
                _log.warning(
                    "  entities: %s",
                    ", ".join(entity_refs[:10]),
                )

    handler.stats = stats  # type: ignore[attr-defined]
    return handler


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    try:
        asyncio.run(_run(args.config))
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
