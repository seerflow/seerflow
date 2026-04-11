"""Tests for WebSocket streaming (ConnectionManager, ClientFilter)."""

from __future__ import annotations

import asyncio
import json as _json
import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import msgspec
import pytest
from fastapi import WebSocketException

from seerflow.api.ws import (
    ClientFilter,
    ConnectionManager,
    serialize_alert,
    serialize_event,
)
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent


def _decode_sent(ws_mock: Any) -> list[dict[str, Any]]:
    """Decode all JSON payloads that were passed to a mocked ``send_bytes``."""
    return [msgspec.json.decode(call.args[0]) for call in ws_mock.send_bytes.await_args_list]


def _make_event(
    *,
    source_type: str = "syslog",
    severity_id: int = 3,
    template_id: int = 42,
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_800_000_000_000_000_000,
        observed_ns=1_800_000_000_000_000_001,
        message="test event",
        source_type=source_type,
        severity_id=severity_id,  # type: ignore[arg-type]
        template_id=template_id,
    )


def _make_alert(
    *,
    alert_type: str = "sigma",
    severity: int = 4,
) -> Alert:
    return Alert(
        alert_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"alert-{alert_type}-{severity}")),
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_800_000_000_000_000_000,
        severity_id=severity,  # type: ignore[arg-type]
        rule_name="test-rule",
        description="test alert",
        entity_uuid=str(uuid.uuid4()),
        entity_value="10.0.0.1",
        entity_type="ip",
        contributing_events=(),
    )


async def _wait_until(
    predicate: Callable[[], bool],
    timeout: float = 1.0,
    interval: float = 0.005,
) -> None:
    """Poll ``predicate`` at ``interval`` seconds until it returns True.

    Replaces fixed ``asyncio.sleep(...)`` test waits that were flaky under
    CI load. Raises ``TimeoutError`` if ``timeout`` seconds elapse without
    ``predicate`` returning a truthy value.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    if not predicate():
        msg = f"predicate did not become true within {timeout}s"
        raise TimeoutError(msg)


class TestWaitUntil:
    """Cover the _wait_until test helper itself so it is not dead code
    before Task 24 replaces fixed sleeps with calls into it."""

    @pytest.mark.asyncio
    async def test_returns_immediately_when_predicate_already_true(self) -> None:
        await _wait_until(lambda: True, timeout=0.1)

    @pytest.mark.asyncio
    async def test_returns_when_predicate_becomes_true(self) -> None:
        calls = {"n": 0}

        def predicate() -> bool:
            calls["n"] += 1
            return calls["n"] >= 3

        await _wait_until(predicate, timeout=0.5, interval=0.001)
        assert calls["n"] >= 3

    @pytest.mark.asyncio
    async def test_raises_timeout_error_when_predicate_never_true(self) -> None:
        with pytest.raises(TimeoutError, match="did not become true"):
            await _wait_until(lambda: False, timeout=0.02, interval=0.001)


class TestClientFilterDefaults:
    def test_empty_filter_matches_any_event(self) -> None:
        f = ClientFilter()
        assert f.matches_event(_make_event()) is True

    def test_empty_filter_matches_any_alert(self) -> None:
        f = ClientFilter()
        assert f.matches_alert(_make_alert()) is True


class TestClientFilterMatching:
    def test_source_filter_matches_whitelisted_source(self) -> None:
        f = ClientFilter(sources=frozenset({"syslog"}))
        assert f.matches_event(_make_event(source_type="syslog")) is True

    def test_source_filter_rejects_non_whitelisted_source(self) -> None:
        f = ClientFilter(sources=frozenset({"syslog"}))
        assert f.matches_event(_make_event(source_type="otlp-grpc")) is False

    def test_min_severity_accepts_equal(self) -> None:
        f = ClientFilter(min_severity=3)
        assert f.matches_event(_make_event(severity_id=3)) is True

    def test_min_severity_rejects_below(self) -> None:
        f = ClientFilter(min_severity=4)
        assert f.matches_event(_make_event(severity_id=3)) is False

    def test_template_filter_matches_whitelisted_template(self) -> None:
        f = ClientFilter(template_ids=frozenset({42}))
        assert f.matches_event(_make_event(template_id=42)) is True

    def test_template_filter_rejects_non_whitelisted_template(self) -> None:
        f = ClientFilter(template_ids=frozenset({42}))
        assert f.matches_event(_make_event(template_id=99)) is False

    def test_alert_type_filter_matches_whitelisted_type(self) -> None:
        f = ClientFilter(alert_types=frozenset({"sigma"}))
        assert f.matches_alert(_make_alert(alert_type="sigma")) is True

    def test_alert_type_filter_rejects_non_whitelisted_type(self) -> None:
        f = ClientFilter(alert_types=frozenset({"ml"}))
        assert f.matches_alert(_make_alert(alert_type="sigma")) is False

    def test_combined_filter_applies_and_semantics(self) -> None:
        f = ClientFilter(
            sources=frozenset({"syslog"}),
            min_severity=3,
            template_ids=frozenset({42}),
        )
        event = _make_event(source_type="syslog", severity_id=4, template_id=42)
        assert f.matches_event(event) is True
        bad_source = _make_event(source_type="otlp-grpc", severity_id=4, template_id=42)
        assert f.matches_event(bad_source) is False


class TestConnectionManagerConstruction:
    def test_default_construction(self) -> None:
        mgr = ConnectionManager()
        assert mgr.connected_count == 0
        assert mgr.max_connections == 20

    def test_custom_parameters(self) -> None:
        mgr = ConnectionManager(
            max_connections=5,
            queue_maxlen=200,
            tick_interval_s=0.05,
            batch_max_events=3,
            status_interval_s=2.0,
        )
        assert mgr.max_connections == 5

    def test_max_connections_is_read_only_property(self) -> None:
        """max_connections and connected_count should both be properties."""
        mgr = ConnectionManager(max_connections=5)
        # Both should be property-based
        assert isinstance(type(mgr).max_connections, property)
        assert isinstance(type(mgr).connected_count, property)
        # Read works
        assert mgr.max_connections == 5
        # Write should fail (property has no setter)
        with pytest.raises(AttributeError):
            mgr.max_connections = 99  # type: ignore[misc]


class TestConnectionManagerLifecycle:
    @pytest.mark.asyncio
    async def test_connect_assigns_unique_id(self) -> None:
        mgr = ConnectionManager()
        ws_a = MagicMock()
        ws_a.accept = AsyncMock()
        ws_b = MagicMock()
        ws_b.accept = AsyncMock()

        id_a = await mgr.connect(ws_a)
        id_b = await mgr.connect(ws_b)

        assert id_a != id_b
        assert mgr.connected_count == 2
        ws_a.accept.assert_awaited_once()
        ws_b.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        client_id = await mgr.connect(ws)

        await mgr.disconnect(client_id)

        assert mgr.connected_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        client_id = await mgr.connect(ws)

        await mgr.disconnect(client_id)
        await mgr.disconnect(client_id)  # Must not raise

        assert mgr.connected_count == 0

    @pytest.mark.asyncio
    async def test_max_connections_enforced(self) -> None:
        mgr = ConnectionManager(max_connections=2)
        for _ in range(2):
            ws = MagicMock()
            ws.accept = AsyncMock()
            await mgr.connect(ws)

        overflow_ws = MagicMock()
        overflow_ws.accept = AsyncMock()
        overflow_ws.close = AsyncMock()
        with pytest.raises(WebSocketException):
            await mgr.connect(overflow_ws)
        assert mgr.connected_count == 2


class TestSetFilter:
    @pytest.mark.asyncio
    async def _connect(self, mgr: ConnectionManager) -> str:
        ws = MagicMock()
        ws.accept = AsyncMock()
        return await mgr.connect(ws)

    @pytest.mark.asyncio
    async def test_valid_filter_updates_state(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)

        errors = mgr.set_filter(
            client_id,
            {
                "type": "filter",
                "sources": ["syslog", "otlp-grpc"],
                "min_severity": 3,
                "alert_types": ["sigma"],
                "template_ids": [42],
            },
        )

        assert errors == []
        client = mgr._clients[client_id]
        assert client.filter.sources == frozenset({"syslog", "otlp-grpc"})
        assert client.filter.min_severity == 3
        assert client.filter.alert_types == frozenset({"sigma"})
        assert client.filter.template_ids == frozenset({42})

    @pytest.mark.asyncio
    async def test_min_severity_clamped_to_lower_bound(self) -> None:
        """Negative severities are clamped to 0 (TRACE)."""
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        mgr.set_filter(client_id, {"type": "filter", "min_severity": -5})
        assert mgr._clients[client_id].filter.min_severity == 0

    @pytest.mark.asyncio
    async def test_min_severity_clamped_to_upper_bound(self) -> None:
        """Severities above FATAL (6) are clamped down to 6."""
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        mgr.set_filter(client_id, {"type": "filter", "min_severity": 99})
        assert mgr._clients[client_id].filter.min_severity == 6

    @pytest.mark.asyncio
    async def test_default_filter_includes_trace_events(self) -> None:
        """Empty ClientFilter must match TRACE (severity=0) events — regression guard."""
        f = ClientFilter()
        assert f.matches_event(_make_event(severity_id=0)) is True

    @pytest.mark.asyncio
    async def test_unknown_alert_type_rejected(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        errors = mgr.set_filter(
            client_id,
            {"type": "filter", "alert_types": ["sigma", "foobar"]},
        )
        assert errors, "expected validation error for unknown alert_type"
        # Filter must NOT be partially applied on failure
        assert mgr._clients[client_id].filter.alert_types == frozenset()

    @pytest.mark.asyncio
    async def test_sources_list_capped_at_50(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        huge = [f"src-{i}" for i in range(100)]
        mgr.set_filter(client_id, {"type": "filter", "sources": huge})
        assert len(mgr._clients[client_id].filter.sources) == 50

    @pytest.mark.asyncio
    async def test_template_ids_list_capped_at_100(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        huge = list(range(500))
        mgr.set_filter(client_id, {"type": "filter", "template_ids": huge})
        assert len(mgr._clients[client_id].filter.template_ids) == 100

    @pytest.mark.asyncio
    async def test_set_filter_on_unknown_client_is_noop(self) -> None:
        mgr = ConnectionManager()
        errors = mgr.set_filter("not-a-real-id", {"type": "filter"})
        assert errors == []


class TestBroadcastEvent:
    @pytest.mark.asyncio
    async def _connect(self, mgr: ConnectionManager) -> str:
        ws = MagicMock()
        ws.accept = AsyncMock()
        return await mgr.connect(ws)

    @pytest.mark.asyncio
    async def test_broadcast_to_empty_manager_is_noop(self) -> None:
        mgr = ConnectionManager()
        mgr.broadcast_event(_make_event())  # Must not raise

    @pytest.mark.asyncio
    async def test_broadcast_appends_to_all_matching_clients(self) -> None:
        mgr = ConnectionManager()
        id_a = await self._connect(mgr)
        id_b = await self._connect(mgr)

        event = _make_event(source_type="syslog")
        mgr.broadcast_event(event)

        assert len(mgr._clients[id_a].event_deque) == 1
        assert len(mgr._clients[id_b].event_deque) == 1

    @pytest.mark.asyncio
    async def test_broadcast_skips_non_matching_clients(self) -> None:
        mgr = ConnectionManager()
        id_syslog = await self._connect(mgr)
        id_otlp = await self._connect(mgr)
        mgr.set_filter(id_syslog, {"type": "filter", "sources": ["syslog"]})
        mgr.set_filter(id_otlp, {"type": "filter", "sources": ["otlp-grpc"]})

        mgr.broadcast_event(_make_event(source_type="syslog"))

        assert len(mgr._clients[id_syslog].event_deque) == 1
        assert len(mgr._clients[id_otlp].event_deque) == 0

    @pytest.mark.asyncio
    async def test_broadcast_sets_wakeup(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        assert mgr._clients[client_id].wakeup.is_set() is False

        mgr.broadcast_event(_make_event())

        assert mgr._clients[client_id].wakeup.is_set() is True

    @pytest.mark.asyncio
    async def test_deque_overflow_drops_oldest_and_increments_counter(self) -> None:
        mgr = ConnectionManager(queue_maxlen=3)
        client_id = await self._connect(mgr)

        for i in range(5):
            mgr.broadcast_event(_make_event(template_id=i))

        client = mgr._clients[client_id]
        assert len(client.event_deque) == 3
        assert client.dropped_events == 2
        template_ids = [be.event.template_id for be in client.event_deque]
        assert template_ids == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_broadcast_does_not_raise_on_filter_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)

        # Corrupt the filter to force a TypeError in matches_event
        mgr._clients[client_id].filter = "not-a-filter"  # type: ignore[assignment]
        mgr.broadcast_event(_make_event())  # Must not raise


class TestBroadcastAlert:
    @pytest.mark.asyncio
    async def _connect(self, mgr: ConnectionManager) -> str:
        ws = MagicMock()
        ws.accept = AsyncMock()
        return await mgr.connect(ws)

    @pytest.mark.asyncio
    async def test_broadcast_alert_appends_to_alert_deque(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)

        mgr.broadcast_alert(_make_alert())

        client = mgr._clients[client_id]
        assert len(client.alert_deque) == 1
        assert len(client.event_deque) == 0  # separate deque

    @pytest.mark.asyncio
    async def test_broadcast_alert_respects_alert_type_filter(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        mgr.set_filter(client_id, {"type": "filter", "alert_types": ["ml"]})

        mgr.broadcast_alert(_make_alert(alert_type="sigma"))
        assert len(mgr._clients[client_id].alert_deque) == 0

        mgr.broadcast_alert(_make_alert(alert_type="ml"))
        assert len(mgr._clients[client_id].alert_deque) == 1

    @pytest.mark.asyncio
    async def test_event_flood_does_not_evict_alerts(self) -> None:
        mgr = ConnectionManager(queue_maxlen=3)
        client_id = await self._connect(mgr)

        mgr.broadcast_alert(_make_alert())
        for i in range(10):
            mgr.broadcast_event(_make_event(template_id=i))

        client = mgr._clients[client_id]
        assert len(client.alert_deque) == 1
        assert len(client.event_deque) == 3
        assert client.dropped_alerts == 0

    @pytest.mark.asyncio
    async def test_alert_deque_overflow_drops_oldest(self) -> None:
        mgr = ConnectionManager(queue_maxlen=2)
        client_id = await self._connect(mgr)

        for i in range(5):
            mgr.broadcast_alert(_make_alert(alert_type="sigma", severity=i + 1))

        client = mgr._clients[client_id]
        assert len(client.alert_deque) == 2
        assert client.dropped_alerts == 3


class TestSerialization:
    def test_serialize_event_has_core_fields(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        event = _make_event(source_type="syslog", severity_id=3, template_id=42)
        payload = serialize_event(BroadcastEvent(event=event))
        assert payload["type"] == "event"
        data = payload["data"]
        assert data["source_type"] == "syslog"
        assert data["severity_id"] == 3
        assert data["template_id"] == 42
        assert "event_id" in data
        assert "timestamp_ns" in data

    def test_serialize_alert_has_core_fields(self) -> None:
        alert = _make_alert(alert_type="sigma", severity=4)
        payload = serialize_alert(alert)
        assert payload["type"] == "alert"
        data = payload["data"]
        assert data["alert_type"] == "sigma"
        assert data["severity"] == 4
        assert "alert_id" in data
        assert "rule_name" in data
        assert "entity_value" in data

    def test_serialize_event_includes_observed_ns_and_severity_text(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        event = _make_event(severity_id=3)
        payload = serialize_event(BroadcastEvent(event=event))
        data = payload["data"]
        assert data["observed_ns"] == event.observed_ns
        assert data["severity_text"] == "Warning"

    def test_serialize_event_is_json_encodable(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        payload = serialize_event(BroadcastEvent(event=_make_event()))
        # Round-trips through json.dumps/loads
        s = _json.dumps(payload)
        parsed = _json.loads(s)
        assert parsed["type"] == "event"

    def test_serialize_event_includes_entity_summary(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        event = msgspec.structs.replace(
            _make_event(),
            related_ips=("10.0.0.1", "10.0.0.2"),
            related_users=("alice",),
        )
        payload = serialize_event(BroadcastEvent(event=event))
        data = payload["data"]
        assert data["entity_summary"] == {
            "ips": ["10.0.0.1", "10.0.0.2"],
            "users": ["alice"],
        }

    def test_entity_summary_omits_empty_keys(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        event = _make_event()  # no related_* fields set
        payload = serialize_event(BroadcastEvent(event=event))
        assert payload["data"]["entity_summary"] == {}

    def test_entity_summary_caps_at_five_values(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        many = tuple(f"10.0.0.{i}" for i in range(20))
        event = msgspec.structs.replace(_make_event(), related_ips=many)
        payload = serialize_event(BroadcastEvent(event=event))
        assert payload["data"]["entity_summary"]["ips"] == list(many[:5])

    def test_serialize_event_without_detection_omits_score_fields(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        payload = serialize_event(BroadcastEvent(event=_make_event()))
        data = payload["data"]
        assert "score" not in data
        assert "is_anomaly" not in data
        assert "upper_threshold" not in data

    def test_serialize_event_with_detection_includes_score_fields(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        be = BroadcastEvent(
            event=_make_event(),
            score=0.87,
            is_anomaly=True,
            upper_threshold=0.8,
        )
        payload = serialize_event(be)
        data = payload["data"]
        assert data["score"] == 0.87
        assert data["is_anomaly"] is True
        assert data["upper_threshold"] == 0.8


class TestClientSender:
    @pytest.mark.asyncio
    async def test_sends_single_event_as_event_message(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.001, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        mgr.broadcast_event(_make_event(source_type="syslog"))
        # Yield control so the sender task can drain
        for _ in range(20):
            await asyncio.sleep(0.005)
            if ws.send_bytes.await_count > 0:
                break

        assert ws.send_bytes.await_count >= 1
        sent = _decode_sent(ws)
        assert sent[0]["type"] == "event"
        await mgr.disconnect(client_id)

    @pytest.mark.asyncio
    async def test_sends_multi_event_as_batch_message(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.05, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        for i in range(5):
            mgr.broadcast_event(_make_event(template_id=i))
        # Wait for at least one drain cycle (one tick_interval)
        await asyncio.sleep(0.12)

        sent = _decode_sent(ws)
        assert len(sent) >= 1
        batch_msg = next((m for m in sent if m.get("type") == "batch"), None)
        assert batch_msg is not None
        assert len(batch_msg["events"]) == 5
        await mgr.disconnect(client_id)

    @pytest.mark.asyncio
    async def test_sends_alerts_separately_from_events(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.05, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        mgr.broadcast_event(_make_event())
        mgr.broadcast_alert(_make_alert())
        await asyncio.sleep(0.12)

        types = [m["type"] for m in _decode_sent(ws)]
        assert "event" in types or "batch" in types
        assert "alert" in types or "alert_batch" in types
        await mgr.disconnect(client_id)

    @pytest.mark.asyncio
    async def test_sender_drains_on_tick_timeout_without_wakeup(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.02, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        # Append directly without setting the wakeup event
        from seerflow.api.ws import BroadcastEvent
        mgr._clients[client_id].event_deque.append(BroadcastEvent(event=_make_event()))
        await asyncio.sleep(0.1)

        assert ws.send_bytes.await_count >= 1
        await mgr.disconnect(client_id)

    @pytest.mark.asyncio
    async def test_sender_exits_on_websocket_disconnect(self) -> None:
        from fastapi import WebSocketDisconnect

        mgr = ConnectionManager(tick_interval_s=0.01, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock(side_effect=WebSocketDisconnect())
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        mgr.broadcast_event(_make_event())
        await asyncio.sleep(0.1)

        # Sender task should have exited on its own.
        client = mgr._clients.get(client_id)
        assert client is not None, "client was removed unexpectedly"
        assert client.sender_task is not None, "sender task should exist"
        assert client.sender_task.done(), "sender task should have exited"
        await mgr.disconnect(client_id)


class TestStatusBroadcaster:
    @pytest.mark.asyncio
    async def test_periodic_status_emitted(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts = AsyncMock(
            return_value=MagicMock(total=17, items=[], has_next=False)
        )
        mgr = ConnectionManager(
            alert_store=alert_store,
            status_interval_s=0.03,
            tick_interval_s=0.01,
        )
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)
        mgr.start_status_task()

        await asyncio.sleep(0.1)

        sent = _decode_sent(ws)
        status_msgs = [m for m in sent if m.get("type") == "status"]
        assert len(status_msgs) >= 1
        data = status_msgs[0]["data"]
        assert "events_ingested_per_sec" in data
        assert data["alerts_24h"] == 17
        assert data["connected_clients"] == 1
        assert data["dropped_events"] == 0
        assert data["dropped_alerts"] == 0

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_events_ingested_per_sec_window_resets(self) -> None:
        mgr = ConnectionManager(
            status_interval_s=0.02,
            tick_interval_s=0.005,
        )
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)
        mgr.start_status_task()

        # Burst 10 events in the first window, then broadcast nothing.
        for _ in range(10):
            mgr.broadcast_event(_make_event())
        await asyncio.sleep(0.15)

        sent = _decode_sent(ws)
        status_msgs = [m for m in sent if m.get("type") == "status"]
        assert len(status_msgs) >= 2
        first_rate = status_msgs[0]["data"]["events_ingested_per_sec"]
        last_rate = status_msgs[-1]["data"]["events_ingested_per_sec"]
        # First window saw the burst; the counter resets after emission,
        # so the last emitted window must show a strictly lower rate.
        assert first_rate > 0.0
        assert last_rate < first_rate
        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_status_payload_includes_dropped_total(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts = AsyncMock(
            return_value=MagicMock(total=0, items=[], has_next=False)
        )
        mgr = ConnectionManager(
            alert_store=alert_store,
            status_interval_s=0.03,
            tick_interval_s=0.01,
            queue_maxlen=2,
        )
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        # Force two drops
        for i in range(5):
            mgr.broadcast_event(_make_event(template_id=i))

        mgr.start_status_task()
        await _wait_until(
            lambda: any(
                msgspec.json.decode(call.args[0]).get("type") == "status"
                for call in ws.send_bytes.await_args_list
            ),
            timeout=1.0,
        )
        sent = _decode_sent(ws)
        status_msgs = [m for m in sent if m.get("type") == "status"]
        assert status_msgs[-1]["data"]["dropped_total"] >= 3
        await mgr.shutdown()


class TestWebSocketRoute:
    def test_router_exists(self) -> None:
        from seerflow.api.ws import router

        assert router is not None
        routes = [r.path for r in router.routes]
        assert "/ws" in routes


class TestSetFilterEdgeCases:
    """Cover the non-list / non-int validation error branches in set_filter."""

    @pytest.mark.asyncio
    async def _connect(self, mgr: ConnectionManager) -> str:
        ws = MagicMock()
        ws.accept = AsyncMock()
        return await mgr.connect(ws)

    @pytest.mark.asyncio
    async def test_non_list_sources_returns_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        errors = mgr.set_filter(client_id, {"type": "filter", "sources": "syslog"})
        assert any("sources must be a list" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_list_template_ids_returns_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        errors = mgr.set_filter(client_id, {"type": "filter", "template_ids": 42})
        assert any("template_ids must be a list" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_list_alert_types_returns_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        errors = mgr.set_filter(client_id, {"type": "filter", "alert_types": "sigma"})
        assert any("alert_types must be a list" in e for e in errors)

    @pytest.mark.asyncio
    async def test_non_int_min_severity_returns_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        errors = mgr.set_filter(client_id, {"type": "filter", "min_severity": "high"})
        assert any("min_severity must be an integer" in e for e in errors)


class TestConnectionManagerEdgeCases:
    """Cover the short-return branches in start_client_sender and start_status_task."""

    @pytest.mark.asyncio
    async def test_start_client_sender_unknown_client_is_noop(self) -> None:
        mgr = ConnectionManager()
        mgr.start_client_sender("not-a-real-id")  # Must not raise

    @pytest.mark.asyncio
    async def test_start_client_sender_twice_is_idempotent(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.01)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)
        first_task = mgr._clients[client_id].sender_task
        mgr.start_client_sender(client_id)  # Second call is no-op
        assert mgr._clients[client_id].sender_task is first_task
        await mgr.disconnect(client_id)

    @pytest.mark.asyncio
    async def test_start_status_task_twice_is_idempotent(self) -> None:
        mgr = ConnectionManager(status_interval_s=3600.0)
        mgr.start_status_task()
        first_task = mgr._status_task
        mgr.start_status_task()  # Second call is no-op
        assert mgr._status_task is first_task
        await mgr.shutdown()


class TestQueryAlerts24h:
    """Cover the _query_alerts_24h exception-handling path."""

    @pytest.mark.asyncio
    async def test_query_failure_returns_zero(self) -> None:
        alert_store = AsyncMock()
        alert_store.query_alerts = AsyncMock(side_effect=RuntimeError("db down"))
        mgr = ConnectionManager(alert_store=alert_store)
        result = await mgr._query_alerts_24h()
        assert result == 0


class TestSenderBatchedAlerts:
    """Cover the alert_batch (multi-alert) send path."""

    @pytest.mark.asyncio
    async def test_sends_multi_alert_as_alert_batch_message(self) -> None:
        mgr = ConnectionManager(tick_interval_s=0.05, batch_max_events=10)
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock()
        client_id = await mgr.connect(ws)
        mgr.start_client_sender(client_id)

        for i in range(4):
            mgr.broadcast_alert(_make_alert(alert_type="sigma", severity=i + 1))
        await asyncio.sleep(0.12)

        sent = _decode_sent(ws)
        alert_batch_msg = next((m for m in sent if m.get("type") == "alert_batch"), None)
        assert alert_batch_msg is not None
        assert len(alert_batch_msg["alerts"]) == 4
        await mgr.disconnect(client_id)


class TestStatusBroadcasterErrorPaths:
    """Cover the status broadcaster send_bytes exception branch."""

    @pytest.mark.asyncio
    async def test_status_send_failure_does_not_crash_task(self) -> None:
        mgr = ConnectionManager(
            status_interval_s=0.02,
            tick_interval_s=0.01,
        )
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_bytes = AsyncMock(side_effect=RuntimeError("broken pipe"))
        client_id = await mgr.connect(ws)
        mgr.start_status_task()
        await asyncio.sleep(0.08)
        # Status task should still be running despite the send failure
        assert mgr._status_task is not None
        assert not mgr._status_task.done()
        await mgr.shutdown()
        await mgr.disconnect(client_id)


class TestBroadcastAlertSafety:
    """Cover the broadcast_alert exception branch (I4 from code review)."""

    @pytest.mark.asyncio
    async def test_broadcast_alert_does_not_raise_on_filter_error(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        client_id = await mgr.connect(ws)
        # Corrupt the filter to force a TypeError inside matches_alert
        mgr._clients[client_id].filter = "not-a-filter"  # type: ignore[assignment]
        mgr.broadcast_alert(_make_alert())  # Must not raise
        await mgr.disconnect(client_id)


class TestBroadcastEventWrapper:
    def test_broadcast_event_namedtuple_has_detection_fields(self) -> None:
        """BroadcastEvent wraps a SeerflowEvent plus optional detection metadata."""
        from seerflow.api.ws import BroadcastEvent

        be = BroadcastEvent(event=_make_event())
        assert be.event is not None
        assert be.score is None
        assert be.is_anomaly is None
        assert be.upper_threshold is None

    def test_broadcast_event_with_detection_fields(self) -> None:
        from seerflow.api.ws import BroadcastEvent

        be = BroadcastEvent(
            event=_make_event(),
            score=0.92,
            is_anomaly=True,
            upper_threshold=0.8,
        )
        assert be.score == 0.92
        assert be.is_anomaly is True
        assert be.upper_threshold == 0.8


class TestOriginAllowlist:
    """CSWSH defense: validate WebSocket Origin against an allowlist."""

    def test_none_allowed_origins_allows_everything(self) -> None:
        """When allowed_origins is None, the manager skips the Origin check."""
        mgr = ConnectionManager()
        assert mgr.is_origin_allowed("http://evil.example.com") is True
        assert mgr.is_origin_allowed(None) is True
        assert mgr.is_origin_allowed("") is True

    def test_empty_allowlist_rejects_all_browser_origins(self) -> None:
        """An explicit empty allowlist rejects every browser connection."""
        mgr = ConnectionManager(allowed_origins=frozenset())
        assert mgr.is_origin_allowed("http://localhost:8080") is False
        # But non-browser clients (no Origin header) are still allowed.
        assert mgr.is_origin_allowed(None) is True

    def test_allowlist_permits_exact_match(self) -> None:
        mgr = ConnectionManager(
            allowed_origins=frozenset({"http://localhost:8080", "http://127.0.0.1:8080"})
        )
        assert mgr.is_origin_allowed("http://localhost:8080") is True
        assert mgr.is_origin_allowed("http://127.0.0.1:8080") is True

    def test_allowlist_rejects_non_matching_origin(self) -> None:
        mgr = ConnectionManager(allowed_origins=frozenset({"http://localhost:8080"}))
        assert mgr.is_origin_allowed("http://evil.example.com") is False
        assert mgr.is_origin_allowed("http://localhost:9999") is False

    def test_allowlist_permits_missing_origin(self) -> None:
        """Non-browser clients (Python, curl) send no Origin header."""
        mgr = ConnectionManager(allowed_origins=frozenset({"http://localhost:8080"}))
        assert mgr.is_origin_allowed(None) is True
        assert mgr.is_origin_allowed("") is True
