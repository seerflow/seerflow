"""PagerDuty Events API v2 sink — trigger/resolve incidents from Seerflow alerts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiohttp

from seerflow.alerting._http import sanitize_body

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.models.alert import Alert
    from seerflow.models.event import SeverityLevel

_log = logging.getLogger("seerflow")

_PD_ENDPOINT = "https://events.pagerduty.com/v2/enqueue"


def _map_severity(severity_id: SeverityLevel) -> str:
    """Map Seerflow SeverityLevel to PagerDuty severity string.

    Mapping:
    - CRITICAL (5) / FATAL (6)  → "critical"
    - ERROR (4)                 → "error"
    - WARNING (3) / NOTICE (2)  → "warning"
    - INFORMATIONAL (1) / TRACE (0) → "info"
    """
    val = int(severity_id)
    if val >= 5:
        return "critical"
    if val >= 4:
        return "error"
    if val >= 2:
        return "warning"
    return "info"


def _build_trigger_payload(alert: Alert, routing_key: str) -> dict[str, object]:
    """Build a PagerDuty Events API v2 trigger payload."""
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"{alert.alert_type}:{alert.rule_name}:{alert.entity_uuid}",
        "payload": {
            "summary": f"{alert.description} [{alert.rule_name}]"[:1024],
            "source": "seerflow",
            "severity": _map_severity(alert.severity_id),
            "timestamp": datetime.fromtimestamp(alert.timestamp_ns / 1e9, tz=UTC).isoformat(),
            "custom_details": {
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type,
                "rule_name": alert.rule_name,
                "entity_value": alert.entity_value,
                "entity_type": alert.entity_type,
                "mitre_tactics": list(alert.mitre_tactics),
                "mitre_techniques": list(alert.mitre_techniques),
                "risk_score": alert.risk_score,
                "contributing_events": [str(e) for e in alert.contributing_events],
            },
        },
    }


def _build_resolve_payload(dedup_key: str, routing_key: str) -> dict[str, object]:
    """Build a PagerDuty Events API v2 resolve payload."""
    return {
        "routing_key": routing_key,
        "event_action": "resolve",
        "dedup_key": dedup_key,
    }


_DEFAULT_RESOLVE_RETRIES = 2
_DEFAULT_RESOLVE_DELAYS: tuple[float, ...] = (1.0,)


async def post_resolve(
    session: aiohttp.ClientSession,
    dedup_key: str,
    routing_key: str,
    *,
    max_retries: int = _DEFAULT_RESOLVE_RETRIES,
    delays: Sequence[float] = _DEFAULT_RESOLVE_DELAYS,
) -> None:
    """POST a resolve event to PagerDuty with bounded retry.

    `max_retries` is the total number of attempts (not retries-after-first).
    Retries on 5xx and network errors. 4xx is logged and not retried.
    """
    payload = _build_resolve_payload(dedup_key, routing_key)
    for attempt in range(max_retries):
        try:
            async with session.post(
                _PD_ENDPOINT,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as resp:
                if resp.status < 400:
                    return
                if resp.status < 500:
                    _log.error("PagerDuty resolve client error %d", resp.status)
                    return
                _log.warning("PagerDuty resolve %d (attempt %d)", resp.status, attempt + 1)
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            # asyncio.CancelledError is BaseException (not Exception) since 3.8
            # and therefore propagates naturally without being caught here.
            _log.warning("PagerDuty resolve failed (attempt %d): %s", attempt + 1, exc)
        if attempt < max_retries - 1:
            sleep_for = delays[attempt] if attempt < len(delays) else delays[-1]
            await asyncio.sleep(sleep_for)
    truncated = dedup_key[:8] + ("..." if len(dedup_key) > 8 else "")
    _log.error(
        "PagerDuty resolve: all %d attempts exhausted for %s",
        max_retries,
        truncated,
    )


@dataclass(frozen=True, slots=True)
class _PagerDutyEvent:
    """Internal queue item for the PagerDuty sink."""

    payload: dict[str, object]


class PagerDutySink:
    """Async queue-backed sink that sends alerts to PagerDuty Events API v2.

    Usage::

        sink = PagerDutySink(routing_key="...", session=session)
        asyncio.create_task(sink.run())
        sink.enqueue_trigger(alert)
        await sink.stop()
    """

    _MAX_RETRIES = 3
    _RETRY_DELAYS = (1.0, 2.0, 4.0)

    def __init__(
        self,
        routing_key: str,
        session: aiohttp.ClientSession,
        queue_maxsize: int = 10_000,
    ) -> None:
        self._routing_key = routing_key
        self._session = session
        self._queue: asyncio.Queue[_PagerDutyEvent] = asyncio.Queue(maxsize=queue_maxsize)
        self._running = True

    def enqueue_trigger(self, alert: Alert) -> None:
        """Enqueue a trigger event. Drops with warning if queue is full."""
        payload = _build_trigger_payload(alert, self._routing_key)
        try:
            self._queue.put_nowait(_PagerDutyEvent(payload=payload))
        except asyncio.QueueFull:
            _log.warning("PagerDuty queue full — dropping alert %s", alert.alert_id)

    def enqueue_resolve(self, dedup_key: str) -> None:
        """Enqueue a resolve event. Drops with warning if queue is full."""
        payload = _build_resolve_payload(dedup_key, self._routing_key)
        try:
            self._queue.put_nowait(_PagerDutyEvent(payload=payload))
        except asyncio.QueueFull:
            truncated = dedup_key[:8] + ("..." if len(dedup_key) > 8 else "")
            _log.warning("PagerDuty queue full — dropping resolve for %s", truncated)

    async def run(self) -> None:
        """Background consumer loop. Runs until stopped and queue is empty."""
        while self._running or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._send(event.payload)
            except Exception:  # intentional programmer-error guard; see S-205
                _log.exception(
                    "PagerDutySink: unexpected error in _send; dropping event and continuing"
                )

    async def stop(self) -> None:
        """Signal the consumer to stop after draining remaining items."""
        self._running = False

    async def _send(self, payload: dict[str, object]) -> None:
        """POST payload to PagerDuty with exponential backoff retry."""
        for attempt in range(self._MAX_RETRIES):
            try:
                async with self._session.post(
                    _PD_ENDPOINT,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                    allow_redirects=False,
                ) as resp:
                    if resp.status < 400:
                        return
                    if resp.status < 500:
                        body = sanitize_body(await resp.text(errors="replace"))
                        _log.error(
                            "PagerDuty returned client error %d — not retrying — response: %s",
                            resp.status,
                            body,
                        )
                        return
                    body = sanitize_body(await resp.text(errors="replace"))
                    _log.warning(
                        "PagerDuty returned %d (attempt %d) — response: %s",
                        resp.status,
                        attempt + 1,
                        body,
                    )
            except (TimeoutError, aiohttp.ClientError, OSError) as exc:
                _log.warning("PagerDuty request failed (attempt %d): %s", attempt + 1, exc)
            if attempt < self._MAX_RETRIES - 1:
                await asyncio.sleep(self._RETRY_DELAYS[attempt])
        _log.error("PagerDuty: all %d retries exhausted", self._MAX_RETRIES)
