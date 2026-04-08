"""Alert webhook dispatcher — async queue + background consumer."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import aiohttp

from seerflow.alerting.formatters import format_json, format_slack, format_teams

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")


def _masked_url(url: str) -> str:
    """Mask a webhook URL to avoid logging embedded auth tokens."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.hostname}/***"


@dataclass(frozen=True, slots=True)
class WebhookTarget:
    """A configured webhook delivery target."""

    url: str = field(repr=False)
    format: str  # "slack" | "teams" | "json"
    min_severity: int = 0


def _format(alert: Alert, fmt: str, *, dashboard_url: str = "") -> dict:  # type: ignore[type-arg]
    """Dispatch to the correct formatter based on format name."""
    if fmt == "slack":
        return format_slack(alert, dashboard_url=dashboard_url)
    if fmt == "teams":
        return format_teams(alert, dashboard_url=dashboard_url)
    return format_json(alert, dashboard_url=dashboard_url)


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
        dashboard_url: str = "",
    ) -> None:
        self._targets = targets
        self._session = session
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True
        self._dashboard_url = dashboard_url

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
            try:
                payload = _format(alert, target.format, dashboard_url=self._dashboard_url)
            except Exception:
                _log.exception(
                    "Formatter failed for target %s, alert %s",
                    _masked_url(target.url),
                    alert.alert_id,
                )
                continue
            try:
                await self._post_with_retry(target, payload, alert.alert_id)
            except Exception:
                _log.exception(
                    "Delivery failed for target %s, alert %s",
                    _masked_url(target.url),
                    alert.alert_id,
                )

    async def _post_with_retry(
        self,
        target: WebhookTarget,
        payload: dict[str, object],
        alert_id: str,
    ) -> None:
        """POST payload to target with exponential backoff retry."""
        for attempt in range(self._MAX_RETRIES):
            try:
                async with self._session.post(
                    target.url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                ) as resp:
                    if resp.status < 400:
                        return
                    if resp.status < 500:
                        _log.error(
                            "Webhook %s returned client error %d for alert %s — not retrying",
                            _masked_url(target.url),
                            resp.status,
                            alert_id,
                        )
                        return
                    _log.warning(
                        "Webhook %s returned %d (attempt %d)",
                        _masked_url(target.url),
                        resp.status,
                        attempt + 1,
                    )
            except Exception as exc:
                _log.warning(
                    "Webhook %s failed (attempt %d): %s",
                    _masked_url(target.url),
                    attempt + 1,
                    exc,
                )
            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        # All retries exhausted — log at ERROR level for monitoring
        _log.error(
            "Webhook %s: all %d retries exhausted for alert %s",
            _masked_url(target.url),
            self._MAX_RETRIES,
            alert_id,
        )
