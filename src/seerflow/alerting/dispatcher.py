"""Alert webhook dispatcher — async queue + background consumer."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting.formatters import format_json, format_slack, format_teams
from seerflow.alerting.mask import mask_webhook_url

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.alerting.router import NotificationRouter
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


def _sanitize_body(raw: str, max_len: int = 200) -> str:
    """Strip control characters and truncate for safe logging."""
    return _CONTROL_CHARS.sub(" ", raw)[:max_len]


@dataclass(frozen=True, slots=True)
class WebhookTarget:
    """A configured webhook delivery target."""

    name: str
    url: str = field(repr=False)
    format: str  # "slack" | "teams" | "json"
    min_severity: int = 0

    async def deliver(self, alert: Alert) -> None:
        # Delivery is driven by AlertDispatcher; WebhookTarget is intentionally
        # a passive config holder. NotificationRouter will call dispatcher-side
        # helpers directly when routing. This stub exists so WebhookTarget
        # satisfies the DeliveryTarget protocol at type-check time.
        raise NotImplementedError(
            "WebhookTarget.deliver is not called directly; "
            "use AlertDispatcher or NotificationRouter."
        )

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        raise NotImplementedError(
            "WebhookTarget.deliver_digest is not called directly; "
            "use AlertDispatcher or NotificationRouter."
        )


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
        router: NotificationRouter | None = None,
    ) -> None:
        self._targets = targets
        self._session = session
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True
        self._dashboard_url = dashboard_url
        self._router = router

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
        if self._router is not None:
            await self._router.route(alert)
            return
        for target in self._targets:
            if int(alert.severity_id) < target.min_severity:
                continue
            try:
                payload = _format(alert, target.format, dashboard_url=self._dashboard_url)
            except Exception:
                _log.exception(
                    "Formatter failed for target %s, alert %s",
                    mask_webhook_url(target.url),
                    alert.alert_id,
                )
                continue
            try:
                await self._post_with_retry(target, payload, alert.alert_id)
            except Exception:
                _log.exception(
                    "Delivery failed for target %s, alert %s",
                    mask_webhook_url(target.url),
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
                        body = _sanitize_body(await resp.text(errors="replace"))
                        _log.error(
                            "Webhook %s returned client error %d for alert %s"
                            " — not retrying — response: %s",
                            mask_webhook_url(target.url),
                            resp.status,
                            alert_id,
                            body,
                        )
                        return
                    body = _sanitize_body(await resp.text(errors="replace"))
                    _log.warning(
                        "Webhook %s returned %d (attempt %d) — response: %s",
                        mask_webhook_url(target.url),
                        resp.status,
                        attempt + 1,
                        body,
                    )
            except Exception as exc:
                _log.warning(
                    "Webhook %s failed (attempt %d): %s",
                    mask_webhook_url(target.url),
                    attempt + 1,
                    exc,
                )
            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        # All retries exhausted — log at ERROR level for monitoring
        _log.error(
            "Webhook %s: all %d retries exhausted for alert %s",
            mask_webhook_url(target.url),
            self._MAX_RETRIES,
            alert_id,
        )


@dataclass(frozen=True, slots=True)
class _WebhookDeliveryAdapter:
    """Adapts a WebhookTarget to DeliveryTarget by routing deliveries through
    AlertDispatcher's existing post-with-retry pipeline."""

    name: str
    min_severity: int
    _target: WebhookTarget
    _dispatcher: AlertDispatcher

    async def deliver(self, alert: Alert) -> None:
        payload = _format(
            alert, self._target.format, dashboard_url=self._dispatcher._dashboard_url
        )
        await self._dispatcher._post_with_retry(self._target, payload, alert.alert_id)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        for alert in alerts:
            await self.deliver(alert)


def build_webhook_delivery_targets(
    dispatcher: AlertDispatcher,
) -> tuple[_WebhookDeliveryAdapter, ...]:
    """Produce DeliveryTarget adapters wired to dispatcher's retry pipeline."""
    return tuple(
        _WebhookDeliveryAdapter(
            name=t.name, min_severity=t.min_severity, _target=t, _dispatcher=dispatcher
        )
        for t in dispatcher._targets
    )
