"""File alert sink — append alerts as rotating NDJSON (S-313, FR-072).

Mirrors the ``ConsoleSink`` queue-backed consumer surface (``enqueue`` /
``run`` / ``stop`` / ``bounds`` / ``close``) but OWNS its output: a stdlib
``logging.handlers`` rotating handler provides append (``mode="a"``),
size/time rollover, and ``backupCount``-bounded segment retention. One alert
is serialized per line via ``formatters.format_json`` (same dict as
``export alerts``), written and flushed immediately so a crash loses at most
the in-flight item, never an export-interval window.
"""

from __future__ import annotations

import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import TYPE_CHECKING, Literal

from seerflow.alerting.formatters import format_json

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5
_DEFAULT_INTERVAL_SECONDS = 86_400


def _build_handler(
    path: str,
    rotation: Literal["size", "time"],
    max_bytes: int,
    interval_seconds: int,
    backup_count: int,
) -> logging.Handler:
    """Construct a stdlib rotating handler (append mode, delayed open)."""
    if rotation == "time":
        return TimedRotatingFileHandler(
            path,
            when="S",
            interval=interval_seconds,
            backupCount=backup_count,
            delay=True,
            encoding="utf-8",
        )
    return RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        delay=True,
        encoding="utf-8",
    )


class FileSink:
    """Async queue-backed sink that appends alerts as rotating NDJSON.

    Usage::

        sink = FileSink("/var/log/seerflow/alerts.ndjson")
        asyncio.create_task(sink.run())
        sink.enqueue(alert)
        await sink.stop()
        await sink.close()
    """

    def __init__(
        self,
        path: str,
        *,
        rotation: Literal["size", "time"] = "size",
        max_bytes: int = _DEFAULT_MAX_BYTES,
        interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
        backup_count: int = _DEFAULT_BACKUP_COUNT,
        min_severity: int = 0,
        queue_maxsize: int = 10_000,
    ) -> None:
        if rotation not in ("size", "time"):
            raise ValueError(f"FileSink rotation must be 'size' or 'time', got {rotation!r}")
        self._path = path
        self._min_severity = min_severity
        self._handler = _build_handler(
            path, rotation, max_bytes, interval_seconds, backup_count
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True
        self._dropped_count = 0

    def _write_alert(self, alert: Alert) -> None:
        """Render + emit one alert via the rotating handler, honoring the floor."""
        if int(alert.severity_id) < self._min_severity:
            return
        line = json.dumps(format_json(alert), separators=(",", ":"), default=str)
        record = logging.LogRecord(
            name="seerflow.filesink",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=line,
            args=(),
            exc_info=None,
        )
        self._handler.emit(record)
        self._handler.flush()

    def _close_handler(self) -> None:
        self._handler.close()

    def enqueue(self, alert: Alert) -> None:
        """Add an alert to the pending queue. Drops with warning if full."""
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            self._dropped_count += 1
            _log.warning("File sink queue full — dropping alert %s", alert.alert_id)

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot."""
        return {
            "current": self._queue.qsize(),
            "max": self._queue.maxsize,
            "evictions": self._dropped_count,
        }

    async def run(self) -> None:
        """Background consumer loop. Runs until stopped and queue is empty."""
        while self._running or not self._queue.empty():
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                self._write_alert(alert)
            except Exception:  # intentional programmer-error guard; see S-205
                _log.exception("FileSink: unexpected error writing alert; continuing")

    async def stop(self) -> None:
        """Signal the consumer to stop after draining remaining items."""
        self._running = False

    async def close(self) -> None:
        """Flush and close the OWNED rotating handler (unlike ConsoleSink)."""
        self._close_handler()
