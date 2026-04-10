"""Tests for WebSocket streaming (ConnectionManager, ClientFilter)."""

from __future__ import annotations

import uuid

import pytest

from seerflow.api.ws import ClientFilter
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent


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


from seerflow.api.ws import ConnectionManager


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


from unittest.mock import AsyncMock, MagicMock

from fastapi import WebSocketException


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
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        mgr.set_filter(client_id, {"type": "filter", "min_severity": 0})
        assert mgr._clients[client_id].filter.min_severity == 1

    @pytest.mark.asyncio
    async def test_min_severity_clamped_to_upper_bound(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)
        mgr.set_filter(client_id, {"type": "filter", "min_severity": 99})
        assert mgr._clients[client_id].filter.min_severity == 24

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
        template_ids = [e.template_id for e in client.event_deque]
        assert template_ids == [2, 3, 4]

    @pytest.mark.asyncio
    async def test_broadcast_does_not_raise_on_filter_error(self) -> None:
        mgr = ConnectionManager()
        client_id = await self._connect(mgr)

        # Corrupt the filter to force a TypeError in matches_event
        mgr._clients[client_id].filter = "not-a-filter"  # type: ignore[assignment]
        mgr.broadcast_event(_make_event())  # Must not raise
