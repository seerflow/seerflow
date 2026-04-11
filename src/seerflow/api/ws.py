"""WebSocket streaming for real-time event/alert delivery to the dashboard.

Provides ConnectionManager (fan-out broadcaster), ClientFilter (per-connection
filtering), BroadcastEvent (event + detection metadata wrapper), and the
/api/ws WebSocket route handler.

Filter application timing
-------------------------
Filter updates via the inbound ``{"type": "filter", ...}`` message take
effect on the next ``broadcast_event`` / ``broadcast_alert`` call after
``set_filter`` returns. Events and alerts already queued in the per-client
deque when the filter is updated are delivered under the *previous* filter
— they were matched at broadcast time, not at drain time. Clients that
need immediate filter-tight semantics should expect a small transition
window after updating filters.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import time
import typing
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

import msgspec
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException

from seerflow.models._types import AlertType
from seerflow.models.event import SEVERITY_MAX, SEVERITY_MIN

if TYPE_CHECKING:
    from seerflow.detection.ensemble import DetectionResult
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.protocols import AlertStore

_log = logging.getLogger("seerflow.api.ws")

# Reused across all broadcasts to avoid per-call allocation on the hot path.
_JSON_ENCODER = msgspec.json.Encoder()

_WS_MAX_FRAME_BYTES = 64 * 1024  # 64 KiB cap on inbound filter messages


@dataclass(frozen=True, slots=True)
class ClientFilter:
    """Per-connection filter criteria. Empty collections mean 'match all'.

    ``min_severity`` defaults to 0 (TRACE) so the empty filter truly
    matches everything. Valid severity range is [0, 6] matching the
    ``SeverityLevel`` enum in ``models.event``.
    """

    sources: frozenset[str] = field(default_factory=frozenset)
    min_severity: int = 0
    alert_types: frozenset[str] = field(default_factory=frozenset)
    template_ids: frozenset[int] = field(default_factory=frozenset)

    def matches_event(self, event: SeerflowEvent) -> bool:
        if self.sources and event.source_type not in self.sources:
            return False
        if event.severity_id < self.min_severity:
            return False
        return not (self.template_ids and event.template_id not in self.template_ids)

    def matches_alert(self, alert: Alert) -> bool:
        if self.alert_types and alert.alert_type not in self.alert_types:
            return False
        return alert.severity_id >= self.min_severity


_ENTITY_SUMMARY_MAX_PER_KEY = 5


def _entity_summary(event: SeerflowEvent) -> dict[str, list[str]]:
    """Build a compact entity summary dict for the WS wire payload.

    Includes only non-empty entity lists, capped at
    ``_ENTITY_SUMMARY_MAX_PER_KEY`` values per key, so the frontend can
    display top entities without a REST round-trip.
    """
    summary: dict[str, list[str]] = {}
    for key, vals in (
        ("ips", event.related_ips),
        ("users", event.related_users),
        ("hosts", event.related_hosts),
        ("domains", event.related_domains),
        ("files", event.related_files),
        ("processes", event.related_processes),
    ):
        if vals:
            summary[key] = list(itertools.islice(vals, _ENTITY_SUMMARY_MAX_PER_KEY))
    return summary


def _event_data(be: BroadcastEvent) -> dict[str, Any]:
    """Build the inner ``data`` payload for an event wire message.

    Field parity with REST ``EventResponse`` (see ``api/schemas.py``) so
    dashboard consumers don't need to duplicate serialization logic.
    """
    event = be.event
    data: dict[str, Any] = {
        "event_id": str(event.event_id),
        "timestamp_ns": event.timestamp_ns,
        "observed_ns": event.observed_ns,
        "severity_id": event.severity_id,
        "severity_text": event.severity_id.text,
        "source_type": event.source_type,
        "message": event.message,
        "template_id": event.template_id,
        "entity_refs": list(event.entity_refs),
        "entity_summary": _entity_summary(event),
    }
    if be.score is not None:
        data["score"] = be.score
    if be.is_anomaly is not None:
        data["is_anomaly"] = be.is_anomaly
    if be.upper_threshold is not None:
        data["upper_threshold"] = be.upper_threshold
    return data


def _alert_data(alert: Alert) -> dict[str, Any]:
    """Build the inner ``data`` payload for an alert wire message."""
    return {
        "alert_id": alert.alert_id,
        "timestamp_ns": alert.timestamp_ns,
        "alert_type": alert.alert_type,
        "rule_name": alert.rule_name,
        "severity": alert.severity_id,
        "risk_score": alert.risk_score,
        "entity_uuid": alert.entity_uuid,
        "entity_type": alert.entity_type,
        "entity_value": alert.entity_value,
        "message": alert.description,
        "mitre_tactics": list(alert.mitre_tactics),
        "mitre_techniques": list(alert.mitre_techniques),
        "dedup_count": alert.dedup_count,
    }


def serialize_event(be: BroadcastEvent) -> dict[str, Any]:
    """Serialize a BroadcastEvent to a dict suitable for JSON wire format."""
    return {"type": "event", "data": _event_data(be)}


def serialize_alert(alert: Alert) -> dict[str, Any]:
    """Serialize an Alert to a dict suitable for JSON wire format."""
    return {"type": "alert", "data": _alert_data(alert)}


class BroadcastEvent(NamedTuple):
    """Event plus optional detection metadata for the WS event deque.

    ``score``, ``is_anomaly``, and ``upper_threshold`` are set when the
    pipeline calls ``broadcast_event`` after ``DetectionEnsemble.process_event``;
    they remain ``None`` when detection hasn't run (tests, kill-chain replay).
    """

    event: SeerflowEvent
    score: float | None = None
    is_anomaly: bool | None = None
    upper_threshold: float | None = None


@dataclass(slots=True)
class ClientState:
    """Runtime state for one connected WebSocket client."""

    client_id: str
    websocket: WebSocket
    filter: ClientFilter
    event_deque: deque[BroadcastEvent]
    alert_deque: deque[Alert]
    wakeup: asyncio.Event
    sender_task: asyncio.Task[None] | None = None
    dropped_events: int = 0
    dropped_alerts: int = 0
    last_filter_ns: int = 0
    dead: bool = False


class ConnectionManager:
    """Fan-out WebSocket broadcaster with per-client filtering and backpressure."""

    # Single source of truth: track the AlertType Literal defined in models/_types.py.
    _VALID_ALERT_TYPES: frozenset[str] = frozenset(typing.get_args(AlertType))
    _MAX_SOURCES = 50
    _MAX_TEMPLATE_IDS = 100
    _MAX_ALERT_TYPES = 10

    def __init__(
        self,
        alert_store: AlertStore | None = None,
        max_connections: int = 20,
        queue_maxlen: int = 1000,
        tick_interval_s: float = 0.01,
        batch_max_events: int = 10,
        status_interval_s: float = 5.0,
        allowed_origins: frozenset[str] | None = None,
        filter_min_interval_ns: int = 100_000_000,  # 100 ms default
    ) -> None:
        self._alert_store = alert_store
        self._max_connections = max_connections
        self._queue_maxlen = queue_maxlen
        self._tick_interval_s = tick_interval_s
        self._batch_max_events = batch_max_events
        self._status_interval_s = status_interval_s
        # ``None`` means "skip Origin check" (non-browser clients / tests).
        # A frozenset means "only browser clients with matching Origin may connect".
        self._allowed_origins = allowed_origins
        self._filter_min_interval_ns = filter_min_interval_ns
        self._clients: dict[str, ClientState] = {}
        self._events_broadcast_count = 0
        # Initialize window start at construction so broadcasts before
        # start_status_task are attributed to a non-zero window.
        self._broadcast_window_start_ns = time.monotonic_ns()
        self._status_task: asyncio.Task[None] | None = None

    @property
    def max_connections(self) -> int:
        return self._max_connections

    @property
    def connected_count(self) -> int:
        return len(self._clients)

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Return True iff the given Origin header should be allowed.

        Cross-Site WebSocket Hijacking (CSWSH) defense: the browser fetch
        spec does NOT enforce same-origin for WebSocket handshakes, so the
        server must validate the ``Origin`` header itself. Missing headers
        (non-browser clients) are allowed. If ``allowed_origins`` is
        ``None`` (e.g. for direct ConnectionManager tests), all origins
        are allowed.
        """
        if self._allowed_origins is None:
            return True
        if origin is None or origin == "":
            # Non-browser client — no Origin header is sent by Python/curl.
            return True
        return origin in self._allowed_origins

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a WebSocket connection, register client, return client_id.

        Raises:
            WebSocketException: if ``max_connections`` is already reached.
        """
        if len(self._clients) >= self.max_connections:
            msg = f"max_connections={self.max_connections} reached"
            # Let Starlette perform the close via the exception handler;
            # do not pre-close and raise (that's a redundant double-signal).
            raise WebSocketException(code=1013, reason=msg)

        await websocket.accept()
        client_id = uuid.uuid4().hex
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
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await client.sender_task

    def set_filter(self, client_id: str, filter_msg: dict[str, Any]) -> list[str]:
        """Validate and apply a filter message. Returns list of error strings.

        On validation failure or rate-limit rejection, the existing filter
        is preserved (atomic update).
        """
        client = self._clients.get(client_id)
        if client is None:
            return []

        now_ns = time.monotonic_ns()
        if (
            client.last_filter_ns > 0
            and now_ns - client.last_filter_ns < self._filter_min_interval_ns
        ):
            return [
                f"filter updates throttled: min interval "
                f"{self._filter_min_interval_ns // 1_000_000} ms"
            ]

        errors: list[str] = []
        sources = self._parse_list_field(filter_msg, "sources", str, self._MAX_SOURCES, errors)
        template_ids = self._parse_list_field(
            filter_msg, "template_ids", int, self._MAX_TEMPLATE_IDS, errors
        )
        alert_types = self._parse_alert_types(filter_msg, errors)
        min_sev = self._parse_min_severity(filter_msg, errors)

        if errors:
            return errors

        client.filter = ClientFilter(
            sources=frozenset(sources),
            min_severity=min_sev,
            alert_types=frozenset(alert_types),
            template_ids=frozenset(template_ids),
        )
        client.last_filter_ns = now_ns
        return []

    def _parse_list_field(
        self,
        filter_msg: dict[str, Any],
        key: str,
        item_type: type,
        cap: int,
        errors: list[str],
    ) -> list[Any]:
        """Parse and cap a list field from a filter message.

        Non-matching element types are rejected with an error rather than
        silently coerced — a client sending ``{"sources": [1, 2]}`` gets
        a clear error instead of a filter that secretly matches nothing.
        """
        raw = filter_msg.get(key, [])
        if not isinstance(raw, list):
            errors.append(f"{key} must be a list")
            return []
        trimmed = raw[:cap]
        if item_type is str:
            if not all(isinstance(v, str) for v in trimmed):
                errors.append(f"{key} items must be strings")
                return []
            return list(trimmed)
        # item_type is int — reject bool since isinstance(True, int) is True
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in trimmed):
            errors.append(f"{key} items must be integers")
            return []
        return list(trimmed)

    def _parse_alert_types(
        self,
        filter_msg: dict[str, Any],
        errors: list[str],
    ) -> list[str]:
        """Parse and validate ``alert_types`` against the allowlist."""
        raw = filter_msg.get("alert_types", [])
        if not isinstance(raw, list):
            errors.append("alert_types must be a list")
            return []
        trimmed = raw[: self._MAX_ALERT_TYPES]
        unknown = [at for at in trimmed if at not in self._VALID_ALERT_TYPES]
        if unknown:
            errors.append(f"unknown alert_types: {unknown}")
        return [at for at in trimmed if at in self._VALID_ALERT_TYPES]

    def _parse_min_severity(
        self,
        filter_msg: dict[str, Any],
        errors: list[str],
    ) -> int:
        """Parse and clamp ``min_severity`` to the valid range."""
        raw = filter_msg.get("min_severity", 1)
        if not isinstance(raw, int) or isinstance(raw, bool):
            errors.append("min_severity must be an integer")
            return 1
        return max(SEVERITY_MIN, min(SEVERITY_MAX, raw))

    def broadcast_event(
        self,
        event: SeerflowEvent,
        *,
        detection: DetectionResult | None = None,
    ) -> None:
        """Fan-out an event to all matching clients (sync, non-blocking).

        Must never raise — the pipeline hot path depends on this.
        """
        self._events_broadcast_count += 1
        if detection is None:
            be = BroadcastEvent(event=event)
        else:
            be = BroadcastEvent(
                event=event,
                score=detection.score,
                is_anomaly=detection.is_anomaly,
                upper_threshold=detection.upper_threshold,
            )
        for client in self._clients.values():
            if client.dead:
                continue
            try:
                if not client.filter.matches_event(event):
                    continue
                if len(client.event_deque) == client.event_deque.maxlen:
                    client.dropped_events += 1
                client.event_deque.append(be)
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
            if client.dead:
                continue
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
        try:
            while True:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        client.wakeup.wait(),
                        timeout=self._tick_interval_s,
                    )
                # Clearing before draining: any broadcast that arrives while
                # we're awaiting send will re-set wakeup and be picked up on
                # the next iteration. Spurious wakes are harmless.
                client.wakeup.clear()
                await self._drain_events(client)
                await self._drain_alerts(client)
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            client.dead = True
            _log.warning(
                "client sender task failed for %s — marking client dead",
                client.client_id,
                exc_info=True,
            )

    async def _drain_events(self, client: ClientState) -> None:
        """Pop up to ``batch_max_events`` events and send as event/batch."""
        events: list[BroadcastEvent] = []
        while client.event_deque and len(events) < self._batch_max_events:
            events.append(client.event_deque.popleft())
        if len(events) == 1:
            await _send_bytes(client.websocket, serialize_event(events[0]))
        elif events:
            await _send_bytes(
                client.websocket,
                {"type": "batch", "events": [_event_data(be) for be in events]},
            )

    async def _drain_alerts(self, client: ClientState) -> None:
        """Pop up to ``batch_max_events`` alerts and send as alert/alert_batch."""
        alerts: list[Alert] = []
        while client.alert_deque and len(alerts) < self._batch_max_events:
            alerts.append(client.alert_deque.popleft())
        if len(alerts) == 1:
            await _send_bytes(client.websocket, serialize_alert(alerts[0]))
        elif alerts:
            await _send_bytes(
                client.websocket,
                {"type": "alert_batch", "alerts": [_alert_data(a) for a in alerts]},
            )

    def start_status_task(self) -> None:
        """Start the periodic status broadcaster task."""
        if self._status_task is not None and not self._status_task.done():
            return
        self._broadcast_window_start_ns = time.monotonic_ns()
        self._status_task = asyncio.create_task(self._status_broadcaster())

    async def _status_broadcaster(self) -> None:
        """Emit periodic status messages to all connected clients.

        The inner ``try`` wraps the full per-tick body so any transient
        failure (e.g. a broken ``_query_alerts_24h`` call or a corrupted
        status payload) is logged and the loop continues — the task must
        not terminate silently on a single bad tick.
        """
        while True:
            try:
                await asyncio.sleep(self._status_interval_s)
                await self._emit_status_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.warning("status broadcaster tick failed", exc_info=True)

    async def _emit_status_tick(self) -> None:
        """Compute and broadcast one status tick to all connected clients.

        The reported ``events_ingested_per_sec`` counts *observed broadcasts*
        at the fan-out point, not per-client deliveries. Events filtered out
        by per-client filters or dropped due to deque overflow still count
        toward this rate — it reflects pipeline ingest, not wire throughput.
        """
        now_ns = time.monotonic_ns()
        elapsed_s = (now_ns - self._broadcast_window_start_ns) / 1e9
        events_per_sec = self._events_broadcast_count / elapsed_s if elapsed_s > 0 else 0.0
        self._events_broadcast_count = 0
        self._broadcast_window_start_ns = now_ns

        alerts_24h = await self._query_alerts_24h()

        dropped_total = sum(c.dropped_events + c.dropped_alerts for c in self._clients.values())
        for client in list(self._clients.values()):
            status_msg = {
                "type": "status",
                "data": {
                    "events_ingested_per_sec": events_per_sec,
                    "alerts_24h": alerts_24h,
                    "connected_clients": len(self._clients),
                    "dropped_events": client.dropped_events,
                    "dropped_alerts": client.dropped_alerts,
                    "dropped_total": dropped_total,
                },
            }
            try:
                await _send_bytes(client.websocket, status_msg)
            except Exception:
                _log.debug(
                    "failed to send status to client %s",
                    client.client_id,
                    exc_info=True,
                )

    async def _query_alerts_24h(self) -> int:
        """Query AlertStore for the 24h alert count. Returns 0 on failure."""
        if self._alert_store is None:
            return 0
        try:
            from seerflow.models.query import AlertQuery, TimeRange

            now_ns = time.time_ns()
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
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._status_task
        for client_id in list(self._clients.keys()):
            await self.disconnect(client_id)


async def _send_bytes(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Encode ``payload`` with msgspec and send as bytes over the WebSocket.

    Using ``msgspec.json.Encoder`` + ``send_bytes`` is ~10-30x faster than
    Starlette's ``send_json`` (which uses ``json.dumps``) on the hot path.
    """
    await websocket.send_bytes(_JSON_ENCODER.encode(payload))


router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time event/alert streaming."""
    manager: ConnectionManager = websocket.app.state.ws_manager

    # CSWSH defense: reject browser connections from unapproved origins
    # BEFORE calling accept(). Non-browser clients (Python, curl) send no
    # Origin header and are allowed through unless an allowlist is in force.
    origin = websocket.headers.get("origin")
    if not manager.is_origin_allowed(origin):
        _log.warning("ws connect rejected: origin %r not allowed", origin)
        await websocket.close(code=1008, reason="origin not allowed")
        return

    try:
        client_id = await manager.connect(websocket)
    except WebSocketException as exc:
        _log.info("ws connect rejected: %s", exc.reason)
        return

    manager.start_client_sender(client_id)

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # Extract bytes from binary or text frame
            if "bytes" in message and message["bytes"] is not None:
                raw: bytes = message["bytes"]
            elif "text" in message and message["text"] is not None:
                raw = message["text"].encode("utf-8")
            else:
                continue
            if len(raw) > _WS_MAX_FRAME_BYTES:
                await _send_bytes(
                    websocket,
                    {"type": "error", "message": "message too large"},
                )
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                await _send_bytes(
                    websocket,
                    {"type": "error", "message": "invalid JSON"},
                )
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "filter":
                errors = manager.set_filter(client_id, msg)
                if errors:
                    await _send_bytes(
                        websocket,
                        {"type": "error", "message": "; ".join(errors)},
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(client_id)
