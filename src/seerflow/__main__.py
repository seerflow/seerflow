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

    _log.info("Seerflow %s starting", __version__)

    ensemble = DetectionEnsemble(config.detection)
    pipeline = await build_pipeline(config)

    # Startup banner
    receivers = list(pipeline.manager._receivers.keys())
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
    await pipeline.run(_make_handler(ensemble))
    _log.info("Seerflow stopped")


def _make_handler(
    ensemble: DetectionEnsemble,
) -> Callable[[RawEvent], Awaitable[None]]:
    """Create an event handler that runs detection on each event."""

    async def handler(event: RawEvent) -> None:
        seerflow_event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=event.received_ns,
            observed_ns=time.time_ns(),
            message=event.data.decode("utf-8", errors="replace")[:32768],
            source_type=event.source_type,
            source_id=event.source_id,
        )
        result = ensemble.process_event(seerflow_event)
        if result.is_anomaly:  # pragma: no cover — tested in test_detection_ensemble
            _log.warning(
                "ANOMALY [%s] score=%.3f dir=%s src=%s",
                result.source_type,
                result.score,
                result.anomaly_direction,
                event.source_id,
            )

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
