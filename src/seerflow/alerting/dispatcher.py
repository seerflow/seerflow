"""Alert webhook dispatcher — async queue + background consumer."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from seerflow.alerting._http import post_with_retry
from seerflow.alerting.formatters import format_json, format_slack, format_teams
from seerflow.alerting.mask import mask_webhook_url
from seerflow.alerting.target import loop_deliver_digest

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiohttp

    from seerflow.alerting.router import NotificationRouter
    from seerflow.models.alert import Alert

_log = logging.getLogger("seerflow")

__all__ = [
    "AlertDispatcher",
    "WebhookTarget",
    "build_webhook_delivery_targets",
]


@dataclass(frozen=True, slots=True)
class WebhookTarget:
    """A configured webhook delivery target."""

    name: str
    url: str = field(repr=False)
    format: str  # "slack" | "teams" | "json"
    min_severity: int = 0

    async def deliver(self, alert: Alert) -> None:
        """Stub: real delivery goes through ``_WebhookDeliveryAdapter``.

        Present only so ``WebhookTarget`` satisfies the ``DeliveryTarget``
        protocol structurally. Use ``build_webhook_delivery_targets()`` to
        obtain an adapter that routes through ``AlertDispatcher._post_with_retry``.
        """
        raise NotImplementedError(
            "WebhookTarget.deliver is not called directly; "
            "use AlertDispatcher or NotificationRouter."
        )

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        """Stub — see :meth:`deliver`."""
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
        """Initialize dispatcher.

        When ``router`` is None (default), ``_dispatch`` fans each alert out to
        every entry in ``targets`` directly, respecting per-target
        ``min_severity`` — preserving pre-S-164 behaviour exactly.

        When ``router`` is provided, ``_dispatch`` delegates policy (matching,
        digesting, quiet hours) to the router. ``targets`` is still meaningful
        in that case: callers typically build router-facing delivery adapters
        from it via :func:`build_webhook_delivery_targets`, so the tuple of
        webhook configs stays the single source of truth for outbound URLs,
        retry/masking behaviour, and ``min_severity`` defaults.
        """
        self._targets = targets
        self._session = session
        self._queue: asyncio.Queue[Alert] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True
        self._dashboard_url = dashboard_url
        self._router = router
        # S-082: cumulative drops on backpressure since process start.
        self._dropped_count = 0

    def masked_dashboard_url(self) -> str:
        """Return a host-only form of ``dashboard_url`` safe for log output.

        Empty ``dashboard_url`` (the default) returns ``""`` so log sites
        can skip the field entirely rather than printing a placeholder.
        """
        if not self._dashboard_url:
            return ""
        return mask_webhook_url(self._dashboard_url)

    def __repr__(self) -> str:
        """Explicit repr that never interpolates the raw ``_dashboard_url``.

        Guards against ``logger.info("dispatcher=%s", self)`` ever leaking
        embedded tokens if the class is later converted to a dataclass
        (whose default ``__repr__`` would dump every attribute).
        """
        masked = self.masked_dashboard_url() or "<unset>"
        return (
            f"AlertDispatcher(targets={len(self._targets)}, "
            f"running={self._running}, dashboard_url={masked})"
        )

    def enqueue(self, alert: Alert) -> None:
        """Enqueue an alert for delivery. Drops silently if queue is full."""
        try:
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            self._dropped_count += 1
            _log.warning("Alert dispatch queue full — dropping alert %s", alert.alert_id)

    def bounds(self) -> dict[str, int]:
        """Return the S-082 memory-bounds snapshot."""
        return {
            "current": self._queue.qsize(),
            "max": self._queue.maxsize,
            "evictions": self._dropped_count,
        }

    async def run(self) -> None:
        """Background consumer loop. Runs until stopped and queue is empty.

        When a NotificationRouter is wired, its ``stop()`` runs after the
        queue is drained so digest-mode buffers flush before shutdown.
        """
        while self._running or not self._queue.empty():
            try:
                alert = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            await self._dispatch(alert)
        if self._router is not None:
            await self._router.stop()

    async def stop(self) -> None:
        """Signal the consumer to stop after draining remaining items.

        ``run()`` completes the drain and then calls ``router.stop()`` so
        pending digest-mode buffers are flushed before the process exits.
        """
        self._running = False

    async def _dispatch(self, alert: Alert) -> None:
        """Send the alert to all configured targets, respecting severity filters."""
        if self._router is not None:
            try:
                await self._router.route(alert)
            except Exception:  # intentional programmer-error guard; see S-205
                _log.exception(
                    "AlertDispatcher: unexpected error in router.route;"
                    " dropping alert and continuing"
                )
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
        """POST payload to target with exponential backoff retry.

        Thin wrapper around :func:`seerflow.alerting._http.post_with_retry`
        retained so the adapter in :func:`build_webhook_delivery_targets` and
        existing tests keep calling ``self._post_with_retry(...)`` unchanged.
        """
        await post_with_retry(
            self._session,
            target.url,
            payload,
            masked_for_log=mask_webhook_url(target.url),
            attempts=self._MAX_RETRIES,
            delays=self._RETRY_DELAYS,
        )


@dataclass(frozen=True, slots=True)
class _WebhookDeliveryAdapter:
    """Adapts a WebhookTarget to DeliveryTarget by routing deliveries through
    AlertDispatcher's existing post-with-retry pipeline.

    ``dashboard_url`` is captured at construction time so the adapter does not
    reach into the dispatcher's private state on each delivery.
    """

    name: str
    min_severity: int
    _target: WebhookTarget
    _dispatcher: AlertDispatcher
    # repr=False mirrors the S-171 discipline on AlertDispatcher —
    # the adapter's generated __repr__ must never leak embedded tokens.
    _dashboard_url: str = field(repr=False)

    async def deliver(self, alert: Alert) -> None:
        try:
            payload = _format(alert, self._target.format, dashboard_url=self._dashboard_url)
        except Exception:
            _log.exception(
                "Formatter failed for target %s, alert %s",
                mask_webhook_url(self._target.url),
                alert.alert_id,
            )
            return
        await self._dispatcher._post_with_retry(self._target, payload, alert.alert_id)

    async def deliver_digest(self, alerts: Sequence[Alert]) -> None:
        await loop_deliver_digest(self, alerts)


def build_webhook_delivery_targets(
    dispatcher: AlertDispatcher,
) -> tuple[_WebhookDeliveryAdapter, ...]:
    """Produce DeliveryTarget adapters wired to dispatcher's retry pipeline."""
    return tuple(
        _WebhookDeliveryAdapter(
            name=t.name,
            min_severity=t.min_severity,
            _target=t,
            _dispatcher=dispatcher,
            _dashboard_url=dispatcher._dashboard_url,
        )
        for t in dispatcher._targets
    )
