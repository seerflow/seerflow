"""WebSocket streaming for real-time event/alert delivery to the dashboard.

Provides ConnectionManager (fan-out broadcaster), ClientFilter (per-connection
filtering), and the /api/ws WebSocket route handler.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket

    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.protocols import AlertStore

_log = logging.getLogger("seerflow.api.ws")


@dataclass(frozen=True, slots=True)
class ClientFilter:
    """Per-connection filter criteria. Empty collections mean 'match all'."""

    sources: frozenset[str] = field(default_factory=frozenset)
    min_severity: int = 1
    alert_types: frozenset[str] = field(default_factory=frozenset)
    template_ids: frozenset[int] = field(default_factory=frozenset)

    def matches_event(self, event: SeerflowEvent) -> bool:
        if self.sources and event.source_type not in self.sources:
            return False
        if int(event.severity_id) < self.min_severity:
            return False
        return not (self.template_ids and event.template_id not in self.template_ids)

    def matches_alert(self, alert: Alert) -> bool:
        if self.alert_types and alert.alert_type not in self.alert_types:
            return False
        return int(alert.severity_id) >= self.min_severity


def serialize_event(event: SeerflowEvent) -> dict[str, Any]:
    """Serialize a SeerflowEvent to a dict suitable for JSON wire format."""
    return {
        "type": "event",
        "data": {
            "event_id": str(event.event_id),
            "timestamp_ns": event.timestamp_ns,
            "severity_id": int(event.severity_id),
            "source_type": event.source_type,
            "message": event.message,
            "template_id": event.template_id,
            "entity_refs": list(event.entity_refs),
        },
    }


def serialize_alert(alert: Alert) -> dict[str, Any]:
    """Serialize an Alert to a dict suitable for JSON wire format."""
    return {
        "type": "alert",
        "data": {
            "alert_id": alert.alert_id,
            "timestamp_ns": alert.timestamp_ns,
            "alert_type": alert.alert_type,
            "rule_name": alert.rule_name,
            "severity": int(alert.severity_id),
            "risk_score": alert.risk_score,
            "entity_uuid": alert.entity_uuid,
            "entity_type": alert.entity_type,
            "entity_value": alert.entity_value,
            "message": alert.description,
            "mitre_tactics": list(alert.mitre_tactics),
            "mitre_techniques": list(alert.mitre_techniques),
            "dedup_count": alert.dedup_count,
        },
    }


@dataclass(slots=True)
class ClientState:
    """Runtime state for one connected WebSocket client."""

    client_id: str
    websocket: WebSocket
    filter: ClientFilter
    event_deque: deque[SeerflowEvent]
    alert_deque: deque[Alert]
    wakeup: asyncio.Event
    sender_task: asyncio.Task[None] | None = None
    dropped_events: int = 0
    dropped_alerts: int = 0


class ConnectionManager:
    """Fan-out WebSocket broadcaster with per-client filtering and backpressure."""

    def __init__(
        self,
        alert_store: AlertStore | None = None,
        max_connections: int = 20,
        queue_maxlen: int = 1000,
        tick_interval_s: float = 0.01,
        batch_max_events: int = 10,
        status_interval_s: float = 5.0,
    ) -> None:
        self._alert_store = alert_store
        self.max_connections = max_connections
        self._queue_maxlen = queue_maxlen
        self._tick_interval_s = tick_interval_s
        self._batch_max_events = batch_max_events
        self._status_interval_s = status_interval_s
        self._clients: dict[str, ClientState] = {}
        self._events_broadcast_count = 0
        self._broadcast_window_start_ns = 0
        self._status_task: asyncio.Task[None] | None = None

    @property
    def connected_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a WebSocket connection, register client, return client_id.

        Raises:
            WebSocketException: if ``max_connections`` is already reached.
        """
        from fastapi import WebSocketException

        if len(self._clients) >= self.max_connections:
            await websocket.close(code=1013)  # Try Again Later
            msg = f"max_connections={self.max_connections} reached"
            raise WebSocketException(code=1013, reason=msg)

        await websocket.accept()
        import uuid as _uuid

        client_id = _uuid.uuid4().hex
        client = ClientState(
            client_id=client_id,
            websocket=websocket,
            filter=ClientFilter(),
            event_deque=deque(maxlen=self._queue_maxlen),
            alert_deque=deque(maxlen=self._queue_maxlen),
            wakeup=asyncio.Event(),
        )
        self._clients[client_id] = client
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove client and cancel its sender task. Idempotent."""
        client = self._clients.pop(client_id, None)
        if client is None:
            return
        if client.sender_task is not None and not client.sender_task.done():
            client.sender_task.cancel()
            try:
                await client.sender_task
            except (asyncio.CancelledError, Exception):
                pass

    _VALID_ALERT_TYPES: frozenset[str] = frozenset(
        {"ml", "sigma", "correlation", "ueba", "ioc"}
    )
    _MAX_SOURCES = 50
    _MAX_TEMPLATE_IDS = 100
    _MAX_ALERT_TYPES = 10
    _SEVERITY_MIN = 1
    _SEVERITY_MAX = 24

    def set_filter(self, client_id: str, filter_msg: dict[str, Any]) -> list[str]:
        """Validate and apply a filter message. Returns list of error strings.

        On validation failure, the existing filter is preserved (atomic update).
        """
        client = self._clients.get(client_id)
        if client is None:
            return []

        errors: list[str] = []

        sources_raw = filter_msg.get("sources", [])
        if not isinstance(sources_raw, list):
            errors.append("sources must be a list")
            sources_raw = []
        sources = frozenset(str(s) for s in sources_raw[: self._MAX_SOURCES])

        templates_raw = filter_msg.get("template_ids", [])
        if not isinstance(templates_raw, list):
            errors.append("template_ids must be a list")
            templates_raw = []
        template_ids = frozenset(
            int(t) for t in templates_raw[: self._MAX_TEMPLATE_IDS] if isinstance(t, int)
        )

        alert_types_raw = filter_msg.get("alert_types", [])
        if not isinstance(alert_types_raw, list):
            errors.append("alert_types must be a list")
            alert_types_raw = []
        alert_types_trimmed = alert_types_raw[: self._MAX_ALERT_TYPES]
        unknown = [
            at for at in alert_types_trimmed if at not in self._VALID_ALERT_TYPES
        ]
        if unknown:
            errors.append(f"unknown alert_types: {unknown}")
        alert_types = frozenset(
            at for at in alert_types_trimmed if at in self._VALID_ALERT_TYPES
        )

        min_sev_raw = filter_msg.get("min_severity", 1)
        if not isinstance(min_sev_raw, int):
            errors.append("min_severity must be an integer")
            min_sev = 1
        else:
            min_sev = max(self._SEVERITY_MIN, min(self._SEVERITY_MAX, min_sev_raw))

        if errors:
            return errors

        client.filter = ClientFilter(
            sources=sources,
            min_severity=min_sev,
            alert_types=alert_types,
            template_ids=template_ids,
        )
        return []

    def broadcast_event(self, event: SeerflowEvent) -> None:
        """Fan-out an event to all matching clients (sync, non-blocking).

        Must never raise — the pipeline hot path depends on this.
        """
        self._events_broadcast_count += 1
        for client in self._clients.values():
            try:
                if not client.filter.matches_event(event):
                    continue
                if len(client.event_deque) == client.event_deque.maxlen:
                    client.dropped_events += 1
                client.event_deque.append(event)
                client.wakeup.set()
            except Exception:
                _log.warning(
                    "broadcast_event failed for client %s",
                    client.client_id,
                    exc_info=True,
                )

    def broadcast_alert(self, alert: Alert) -> None:
        """Fan-out an alert to all matching clients (sync, non-blocking).

        Must never raise — the pipeline hot path depends on this.
        """
        for client in self._clients.values():
            try:
                if not client.filter.matches_alert(alert):
                    continue
                if len(client.alert_deque) == client.alert_deque.maxlen:
                    client.dropped_alerts += 1
                client.alert_deque.append(alert)
                client.wakeup.set()
            except Exception:
                _log.warning(
                    "broadcast_alert failed for client %s",
                    client.client_id,
                    exc_info=True,
                )

    def start_client_sender(self, client_id: str) -> None:
        """Start the per-client sender task. Called after connect()."""
        client = self._clients.get(client_id)
        if client is None or client.sender_task is not None:
            return
        client.sender_task = asyncio.create_task(self._client_sender(client))

    async def _client_sender(self, client: ClientState) -> None:
        """Drain deques on wakeup or tick timeout; send batched JSON."""
        from fastapi import WebSocketDisconnect

        try:
            while True:
                try:
                    await asyncio.wait_for(
                        client.wakeup.wait(),
                        timeout=self._tick_interval_s,
                    )
                except TimeoutError:
                    pass
                client.wakeup.clear()

                events_to_send: list[SeerflowEvent] = []
                while client.event_deque and len(events_to_send) < self._batch_max_events:
                    events_to_send.append(client.event_deque.popleft())

                if len(events_to_send) == 1:
                    await client.websocket.send_json(serialize_event(events_to_send[0]))
                elif events_to_send:
                    await client.websocket.send_json(
                        {
                            "type": "batch",
                            "events": [serialize_event(e)["data"] for e in events_to_send],
                        }
                    )

                alerts_to_send: list[Alert] = []
                while client.alert_deque and len(alerts_to_send) < self._batch_max_events:
                    alerts_to_send.append(client.alert_deque.popleft())

                if len(alerts_to_send) == 1:
                    await client.websocket.send_json(serialize_alert(alerts_to_send[0]))
                elif alerts_to_send:
                    await client.websocket.send_json(
                        {
                            "type": "alert_batch",
                            "alerts": [serialize_alert(a)["data"] for a in alerts_to_send],
                        }
                    )
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.warning(
                "client sender task failed for %s",
                client.client_id,
                exc_info=True,
            )

    def start_status_task(self) -> None:
        """Start the periodic status broadcaster task."""
        if self._status_task is not None and not self._status_task.done():
            return
        import time as _time

        self._broadcast_window_start_ns = _time.monotonic_ns()
        self._status_task = asyncio.create_task(self._status_broadcaster())

    async def _status_broadcaster(self) -> None:
        """Emit periodic status messages to all connected clients."""
        import time as _time

        try:
            while True:
                await asyncio.sleep(self._status_interval_s)

                now_ns = _time.monotonic_ns()
                elapsed_s = (now_ns - self._broadcast_window_start_ns) / 1e9
                events_per_sec = (
                    self._events_broadcast_count / elapsed_s if elapsed_s > 0 else 0.0
                )
                self._events_broadcast_count = 0
                self._broadcast_window_start_ns = now_ns

                alerts_24h = await self._query_alerts_24h()

                for client in list(self._clients.values()):
                    status_msg = {
                        "type": "status",
                        "data": {
                            "events_per_sec": events_per_sec,
                            "alerts_24h": alerts_24h,
                            "connected_clients": len(self._clients),
                            "dropped_events": client.dropped_events,
                            "dropped_alerts": client.dropped_alerts,
                        },
                    }
                    try:
                        await client.websocket.send_json(status_msg)
                    except Exception:
                        _log.debug(
                            "failed to send status to client %s",
                            client.client_id,
                            exc_info=True,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.warning("status broadcaster task crashed", exc_info=True)

    async def _query_alerts_24h(self) -> int:
        """Query AlertStore for the 24h alert count. Returns 0 on failure."""
        if self._alert_store is None:
            return 0
        try:
            import time as _time

            from seerflow.models.query import AlertQuery, TimeRange

            now_ns = _time.time_ns()
            page = await self._alert_store.query_alerts(
                AlertQuery(
                    time_range=TimeRange(
                        start_ns=now_ns - 24 * 3600 * 1_000_000_000,
                        end_ns=now_ns,
                    ),
                    limit=1,
                ),
            )
            return int(page.total)
        except Exception:
            _log.debug("alerts_24h query failed", exc_info=True)
            return 0

    async def shutdown(self) -> None:
        """Cancel the status task and all client sender tasks."""
        if self._status_task is not None and not self._status_task.done():
            self._status_task.cancel()
            try:
                await self._status_task
            except (asyncio.CancelledError, Exception):
                pass
        for client_id in list(self._clients.keys()):
            await self.disconnect(client_id)
