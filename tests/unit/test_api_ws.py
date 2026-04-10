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
