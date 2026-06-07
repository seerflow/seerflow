"""Tests for the sink type registry (S-361/FR-005)."""

from __future__ import annotations

import pytest

from seerflow.alerting.sinks.registry import (
    KNOWN_SINK_TYPES,
    build_sink,
    is_known_sink_type,
)
from seerflow.alerting.target import DeliveryTarget
from seerflow.config import SinkConfig


def test_known_sink_types_includes_console_and_file() -> None:
    assert "console" in KNOWN_SINK_TYPES
    assert "file" in KNOWN_SINK_TYPES


def test_is_known_sink_type() -> None:
    assert is_known_sink_type("console") is True
    assert is_known_sink_type("hec") is False


def test_build_console_sink_returns_delivery_target() -> None:
    target = build_sink(SinkConfig(type="console", name="ops", formatter="json"))
    assert isinstance(target, DeliveryTarget)
    assert target.name == "ops"
    assert target.min_severity == 0


def test_build_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown sink type"):
        build_sink(SinkConfig(type="nope", name="x", formatter="json"))
