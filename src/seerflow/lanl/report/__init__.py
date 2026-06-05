"""LANL benchmark report package (S-358).

Provides frozen, serialisable data types for structured benchmark reports
(:mod:`~seerflow.lanl.report.schema`) and a YAML-backed baselines registry
(:mod:`~seerflow.lanl.report.baselines`).

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
    "load_baselines",
    "render_validation_report",
]
