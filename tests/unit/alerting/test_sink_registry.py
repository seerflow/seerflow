"""Tests for the sink type registry (S-361/FR-005)."""

from __future__ import annotations

import uuid

import pytest

from seerflow.alerting.sinks.registry import (
    KNOWN_SINK_TYPES,
    build_sink,
    is_known_sink_type,
)
from seerflow.alerting.target import DeliveryTarget
from seerflow.config import SinkConfig
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def test_known_sink_types_includes_console_and_file() -> None:
    assert "console" in KNOWN_SINK_TYPES
    assert "file" in KNOWN_SINK_TYPES


def test_known_sink_types_includes_otlp() -> None:
    assert "otlp" in KNOWN_SINK_TYPES


def test_is_known_sink_type() -> None:
    assert is_known_sink_type("console") is True
    assert is_known_sink_type("otlp") is True
    assert is_known_sink_type("hec") is False


def test_build_console_sink_returns_delivery_target() -> None:
    target = build_sink(SinkConfig(type="console", name="ops", formatter="json"))
    assert isinstance(target, DeliveryTarget)
    assert target.name == "ops"
    assert target.min_severity == 0


def _make_alert() -> Alert:
    return Alert(
        alert_id=str(uuid.uuid4()),
        alert_type="ml",  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.ERROR,
        rule_name="r",
        description="d",
        entity_uuid="u",
        entity_value="10.0.0.1",
        entity_type="ip",  # type: ignore[arg-type]
        contributing_events=(),
        risk_score=0.5,
        dedup_key="k",
    )


def test_build_otlp_sink_returns_delivery_target() -> None:
    target = build_sink(
        SinkConfig(
            type="otlp",
            name="collector",
            formatter="json",
            min_severity=3,
            options=(("endpoint", "localhost:4317"), ("protocol", "grpc")),
        )
    )
    assert isinstance(target, DeliveryTarget)
    assert target.name == "collector"
    assert target.min_severity == 3


def test_build_otlp_sink_http_protocol() -> None:
    target = build_sink(
        SinkConfig(
            type="otlp",
            name="collector",
            formatter="json",
            options=(("endpoint", "http://localhost:4318"), ("protocol", "http")),
        )
    )
    assert target._sink._protocol == "http"  # type: ignore[attr-defined]


async def test_build_otlp_sink_deliver_enqueues() -> None:
    """deliver() routes the alert onto the wrapped OtlpSink's pending queue."""
    target = build_sink(
        SinkConfig(
            type="otlp",
            name="collector",
            formatter="json",
            options=(("endpoint", "localhost:4317"),),
        )
    )
    await target.deliver(_make_alert())
    assert target._sink.bounds()["current"] == 1  # type: ignore[attr-defined]


async def test_build_otlp_sink_deliver_digest_enqueues_all() -> None:
    """deliver_digest() enqueues each alert onto the wrapped sink."""
    target = build_sink(
        SinkConfig(
            type="otlp",
            name="collector",
            formatter="json",
            options=(("endpoint", "localhost:4317"),),
        )
    )
    await target.deliver_digest([_make_alert(), _make_alert()])
    assert target._sink.bounds()["current"] == 2  # type: ignore[attr-defined]


def test_build_otlp_sink_requires_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        build_sink(SinkConfig(type="otlp", name="x", formatter="json"))


def test_build_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown sink type"):
        build_sink(SinkConfig(type="nope", name="x", formatter="json"))
