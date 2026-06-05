"""Shared factory fixtures for LANL report unit tests (S-359).

Each report test file previously re-declared near-identical
``AccuracySummary`` / ``RunTelemetry`` / ``HostInfo`` construction. These
factory fixtures expose callables with sensible defaults plus ``**overrides``
so each test can keep its own asserted values without repeating the
construction boilerplate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.lanl.report.schema import (
    AccuracySummary,
    HostInfo,
    RunTelemetry,
    ScenarioSummary,
)

if TYPE_CHECKING:
    from collections.abc import Callable


# ---------------------------------------------------------------------------
# Standalone builders — importable by tests that need the trio outside the
# fixture machinery (e.g. test_cli_lanl_report.py constructs all three inline).
# ---------------------------------------------------------------------------


def build_accuracy(**overrides: object) -> AccuracySummary:
    """Build an :class:`AccuracySummary` with sensible defaults + overrides."""
    defaults: dict[str, object] = {
        "precision": 0.90,
        "recall": 0.85,
        "f1": 0.875,
        "auc": 0.90,
        "false_positive_rate": 0.02,
        "true_positives": 90,
        "false_positives": 10,
        "false_negatives": 15,
        "total_alerts": 100,
        "patterns_detected": ("pattern-a",),
        "scenarios": (
            ScenarioSummary(
                name="scenario-default",
                detected=True,
                mttd_seconds=30.0,
                missed_record_count=0,
            ),
        ),
        "missed_attributions": (),
    }
    defaults.update(overrides)
    return AccuracySummary(**defaults)  # type: ignore[arg-type]


def build_telemetry(**overrides: object) -> RunTelemetry:
    """Build a :class:`RunTelemetry` with sensible defaults + overrides."""
    defaults: dict[str, object] = {
        "wall_s": 120.0,
        "events_processed": 46_800,
        "throughput_eps": 390.0,
        "mean_latency_s": 0.0001,
        "peak_rss_mb": 256.0,
    }
    defaults.update(overrides)
    return RunTelemetry(**defaults)  # type: ignore[arg-type]


def build_host(**overrides: object) -> HostInfo:
    """Build a :class:`HostInfo` with sensible defaults + overrides."""
    defaults: dict[str, object] = {
        "cpu_model": "Intel i7-8750H",
        "physical_cores": 6,
        "logical_cores": 12,
        "ram_gb": 16.0,
        "platform": "Linux-5.15",
    }
    defaults.update(overrides)
    return HostInfo(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Factory fixtures — thin wrappers exposing the builders to fixture consumers.
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_accuracy() -> Callable[..., AccuracySummary]:
    """Factory for :class:`AccuracySummary` with overridable defaults."""
    return build_accuracy


@pytest.fixture()
def make_telemetry() -> Callable[..., RunTelemetry]:
    """Factory for :class:`RunTelemetry` with overridable defaults."""
    return build_telemetry


@pytest.fixture()
def make_host() -> Callable[..., HostInfo]:
    """Factory for :class:`HostInfo` with overridable defaults."""
    return build_host
