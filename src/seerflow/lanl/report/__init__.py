"""LANL benchmark report package (S-358).

Provides frozen, serialisable data types for structured benchmark reports
(:mod:`~seerflow.lanl.report.schema`) and a YAML-backed baselines registry
(:mod:`~seerflow.lanl.report.baselines`).

Slice 2 adds hardware detection (:mod:`~seerflow.lanl.report.hardware`) and
the pure report builder (:mod:`~seerflow.lanl.report.build`).

The legacy Markdown renderer (``render_validation_report``, ``_main``) is
preserved in :mod:`seerflow.lanl.report_renderer` and re-exported here so
existing callers that import from ``seerflow.lanl.report`` keep working
without changes.

The ``__main__`` block is also wired through so
``python -m seerflow.lanl.report`` continues to work via
``seerflow.lanl.report_renderer``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Baselines re-exports
# ---------------------------------------------------------------------------
from seerflow.lanl.report.baselines import load_baselines

# ---------------------------------------------------------------------------
# Build re-exports (slice 2)
# ---------------------------------------------------------------------------
from seerflow.lanl.report.build import build_report

# ---------------------------------------------------------------------------
# Hardware re-exports (slice 2)
# ---------------------------------------------------------------------------
from seerflow.lanl.report.hardware import detect_host, project

# ---------------------------------------------------------------------------
# Schema re-exports
# ---------------------------------------------------------------------------
from seerflow.lanl.report.schema import (
    FIRST_ATTACK_EVENTS,
    TOTAL_EVENTS,
    AccuracySummary,
    Baseline,
    ComparisonRow,
    HostInfo,
    Projection,
    Report,
    RunTelemetry,
    ScenarioSummary,
)

# ---------------------------------------------------------------------------
# Legacy Markdown renderer — preserved for backward compatibility
# ---------------------------------------------------------------------------
from seerflow.lanl.report_renderer import _main, render_validation_report

__all__ = [
    "FIRST_ATTACK_EVENTS",
    "TOTAL_EVENTS",
    "AccuracySummary",
    "Baseline",
    "ComparisonRow",
    "HostInfo",
    "Projection",
    "Report",
    "RunTelemetry",
    "ScenarioSummary",
    "_main",
    "build_report",
    "detect_host",
    "load_baselines",
    "project",
    "render_validation_report",
]
