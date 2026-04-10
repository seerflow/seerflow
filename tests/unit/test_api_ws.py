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
