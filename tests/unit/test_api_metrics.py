"""Tests for api.metrics — PipelineMetrics + provider factory."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from seerflow.api.metrics import PipelineMetrics


class TestPipelineMetrics:
    def test_is_frozen(self) -> None:
        m = PipelineMetrics(
            started_monotonic=100.0,
            total_events_processed=500,
            active_sources=2,
            model_count=8,
        )
        with pytest.raises(FrozenInstanceError):
            m.total_events_processed = 999  # type: ignore[misc]

    def test_field_values(self) -> None:
        m = PipelineMetrics(
            started_monotonic=100.0,
            total_events_processed=500,
            active_sources=2,
            model_count=8,
        )
        assert m.started_monotonic == 100.0
        assert m.total_events_processed == 500
        assert m.active_sources == 2
        assert m.model_count == 8
