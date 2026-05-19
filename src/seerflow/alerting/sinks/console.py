"""Console alert sink — write alerts to stdout/stderr (human or NDJSON).

Mirrors the ``PagerDutySink`` queue-backed consumer surface (S-312, FR-071):
``enqueue`` / ``run`` / ``stop`` / ``bounds`` / ``close``. Unlike ``OtlpSink``
there is NO export interval — every alert is written and flushed immediately so
a headless operator sees it within NFR-015's 1 s budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import IO, TYPE_CHECKING, Literal

from seerflow.alerting.formatters import format_json

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_DESC_MAX = 200


def _resolve_stream(stream: IO[str] | Literal["stdout", "stderr"]) -> IO[str]:
    """Resolve a named stream to ``sys.stdout``/``sys.stderr``.

    A non-string value is treated as an already-open text stream (the test
    seam — ``io.StringIO``). The sink never owns/closes the resolved stream.
    """
    if stream == "stdout":
        return sys.stdout
    if stream == "stderr":
        return sys.stderr
    return stream


def _human_line(alert: Alert) -> str:
    """One plain, grep-friendly line: severity, rule, entity, risk, description."""
    desc = alert.description[:_DESC_MAX]
    return (
        f"[{alert.severity_id.name}] {alert.rule_name}  "
        f"entity={alert.entity_value} ({alert.entity_type})  "
        f"risk={alert.risk_score:.2f}  {desc}"
    )


class ConsoleSink:
    """Async queue-backed sink that writes alerts to a console stream.

    Usage::

        sink = ConsoleSink("stdout", fmt="human")
        asyncio.create_task(sink.run())
        sink.enqueue(alert)
        await sink.stop()
    """

    def __init__(
        self,
        stream: IO[str] | Literal["stdout", "stderr"],
        *,
        fmt: Literal["human", "json"] = "human",
        min_severity: int = 0,
        queue_maxsize: int = 10_000,
    ) -> None:
        if fmt not in ("human", "json"):
            raise ValueError(f"ConsoleSink fmt must be 'human' or 'json', got {fmt!r}")
        self._stream = _resolve_stream(stream)
        self._fmt = fmt
        self._min_severity = min_severity
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True
        self._dropped_count = 0

    def _write_alert(self, alert: Alert) -> None:
        """Render + write + flush one alert, honoring the severity floor."""
        if int(alert.severity_id) < self._min_severity:
            return
        if self._fmt == "json":
            line = json.dumps(format_json(alert), separators=(",", ":"), default=str)
        else:
            line = _human_line(alert)
        self._stream.write(line + "\n")
        self._stream.flush()

    def enqueue(self, alert: Alert) -> None:
        """Add an alert to the pending queue. Drops with warning if full."""
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            self._dropped_count += 1
            _log.warning("Console sink queue full — dropping alert %s", alert.alert_id)

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
                _log.exception("ConsoleSink: unexpected error writing alert; continuing")

    async def stop(self) -> None:
        """Signal the consumer to stop after draining remaining items."""
        self._running = False

    async def close(self) -> None:
        """No-op — the stream is borrowed, never owned (closing stdout breaks the process)."""
