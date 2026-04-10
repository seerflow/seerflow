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
