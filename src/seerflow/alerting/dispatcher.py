"""Alert webhook dispatcher — async queue + background consumer."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting.formatters import format_json, format_slack, format_teams

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")


@dataclass(frozen=True, slots=True)
class WebhookTarget:
    """A configured webhook delivery target."""

    url: str
    format: str  # "slack" | "teams" | "json"
    min_severity: int = 0


def _format(alert: Alert, fmt: str) -> dict:  # type: ignore[type-arg]
    """Dispatch to the correct formatter based on format name."""
    if fmt == "slack":
        return format_slack(alert)
    if fmt == "teams":
        return format_teams(alert)
    return format_json(alert)


class AlertDispatcher:
    """Async queue-backed dispatcher that POSTs alerts to webhook targets.

    Usage::

        dispatcher = AlertDispatcher(targets=(...), session=session)
        asyncio.create_task(dispatcher.run())   # start background consumer
        dispatcher.enqueue(alert)               # call from pipeline handler
        await dispatcher.stop()                 # signal shutdown (drains queue)
    """

    _MAX_RETRIES = 3
    _RETRY_DELAYS = (1.0, 2.0, 4.0)

    def __init__(
        self,
        targets: tuple[WebhookTarget, ...],
        session: aiohttp.ClientSession,
        queue_maxsize: int = 10_000,
    ) -> None:
        self._targets = targets
        self._session = session
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True

    def enqueue(self, alert: Alert) -> None:
        """Enqueue an alert for delivery. Drops silently if queue is full."""
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            _log.warning("Alert dispatch queue full — dropping alert %s", alert.alert_id)

    async def run(self) -> None:
        """Background consumer loop. Runs until stopped and queue is empty."""
        while self._running or not self._queue.empty():
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._dispatch(alert)

    async def stop(self) -> None:
        """Signal the consumer to stop after draining remaining items."""
        self._running = False

    async def _dispatch(self, alert: Alert) -> None:
        """Send the alert to all configured targets, respecting severity filters."""
        for target in self._targets:
            if int(alert.severity_id) < target.min_severity:
                continue
            payload = _format(alert, target.format)
            for attempt in range(self._MAX_RETRIES):
                try:
                    async with self._session.post(
                        target.url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status < 400:
                            break
                        _log.warning(
                            "Webhook %s returned %d (attempt %d)",
                            target.url,
                            resp.status,
                            attempt + 1,
                        )
                except Exception:
                    _log.warning("Webhook %s failed (attempt %d)", target.url, attempt + 1)
                if attempt < self._MAX_RETRIES - 1:
                    await asyncio.sleep(self._RETRY_DELAYS[attempt])
