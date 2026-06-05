"""Frozen, msgspec-serialisable data types for a LANL benchmark report (S-358).

All public types are ``msgspec.Struct`` instances with ``frozen=True`` so they
round-trip losslessly via ``msgspec.json.encode`` / ``msgspec.json.decode`` and
cannot be mutated after construction.

Constants
---------
TOTAL_EVENTS       — full LANL dataset event count (1.6 B).
FIRST_ATTACK_EVENTS — subset of events with red-team activity.
"""

from __future__ import annotations

from typing import Any

import msgspec

# ---------------------------------------------------------------------------
# Dataset constants (full LANL Unified Host and Network Dataset v2)
# ---------------------------------------------------------------------------

TOTAL_EVENTS: int = 1_607_452_967
FIRST_ATTACK_EVENTS: int = 58_655_985

# ---------------------------------------------------------------------------
# HostInfo
# ---------------------------------------------------------------------------


class HostInfo(msgspec.Struct, frozen=True):
    """Hardware / OS metadata for the machine that ran the benchmark."""

    cpu_model: str | None
    physical_cores: int | None
    logical_cores: int | None
    ram_gb: float | None
    platform: str


# ---------------------------------------------------------------------------
# RunTelemetry
# ---------------------------------------------------------------------------


class RunTelemetry(msgspec.Struct, frozen=True):
    """Wall-clock timing and throughput observed during the benchmark run."""

    wall_s: float
    events_processed: int
    throughput_eps: float
    mean_latency_s: float
    peak_rss_mb: float | None


# ---------------------------------------------------------------------------
# ScenarioSummary
# ---------------------------------------------------------------------------


class ScenarioSummary(msgspec.Struct, frozen=True):
    """Compact per-red-team-scenario detection summary."""

    name: str
    detected: bool
    mttd_seconds: float | None
    missed_record_count: int


# ---------------------------------------------------------------------------
# AccuracySummary
# ---------------------------------------------------------------------------


class AccuracySummary(msgspec.Struct, frozen=True):
    """Read-only projection of a :class:`~seerflow.lanl.validator.ValidationResult`.

    ``f1`` is stored here under the report-friendly name ``f1`` (the
    underlying ``ValidationResult`` uses ``f1_score``).
    """

    precision: float
    recall: float
    f1: float
    auc: float
    false_positive_rate: float
    true_positives: int
    false_positives: int
    false_negatives: int
    total_alerts: int
    patterns_detected: tuple[str, ...]
    scenarios: tuple[ScenarioSummary, ...]
    missed_attributions: tuple[str, ...]

    @classmethod
    def from_validation_result(cls, result: object) -> AccuracySummary:
        """Map a :class:`~seerflow.lanl.validator.ValidationResult` (or a
        :class:`~seerflow.lanl.streaming.StreamingValidationResult`, which
        delegates attribute access via ``__getattr__``) to an
        :class:`AccuracySummary`.

        Tolerates:
        - ``auc`` being ``None`` → normalised to ``0.0``.
        - ``f1_score`` attribute name → mapped to ``f1``.
        - ``patterns_detected`` being a :class:`frozenset` → sorted tuple.
        - ``attack_scenarios`` entries having ``name / detected / mttd_seconds /
          missed_record_count`` attributes.
        - ``missed_attributions`` entries with a ``record_repr`` attribute or
          being plain strings.
        """

        # Use Any so mypy can follow the attribute access on the protocol-duck
        # type (ValidationResult / StreamingValidationResult / SimpleNamespace).
        r: Any = result

        raw_auc: Any = getattr(r, "auc", None)
        auc: float = 0.0 if raw_auc is None else float(raw_auc)

        raw_patterns: Any = getattr(r, "patterns_detected", None) or frozenset()
        patterns: tuple[str, ...] = tuple(sorted(raw_patterns))

        raw_scenarios: Any = getattr(r, "attack_scenarios", None) or ()
        scenarios: tuple[ScenarioSummary, ...] = tuple(
            ScenarioSummary(
                name=str(getattr(sc, "name", "")),
                detected=bool(getattr(sc, "detected", False)),
                mttd_seconds=getattr(sc, "mttd_seconds", None),
                missed_record_count=int(getattr(sc, "missed_record_count", 0)),
            )
            for sc in raw_scenarios
        )

        raw_attrs: Any = getattr(r, "missed_attributions", None) or ()
        missed_attributions: tuple[str, ...] = tuple(
            getattr(ma, "record_repr", str(ma)) for ma in raw_attrs
        )

        return cls(
            precision=float(getattr(r, "precision", 0.0)),
            recall=float(getattr(r, "recall", 0.0)),
            f1=float(getattr(r, "f1_score", 0.0)),
            auc=auc,
            false_positive_rate=float(getattr(r, "false_positive_rate", 0.0)),
            true_positives=int(getattr(r, "true_positives", 0)),
            false_positives=int(getattr(r, "false_positives", 0)),
            false_negatives=int(getattr(r, "false_negatives", 0)),
            total_alerts=int(getattr(r, "total_alerts", 0)),
            patterns_detected=patterns,
            scenarios=scenarios,
            missed_attributions=missed_attributions,
        )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


class Baseline(msgspec.Struct, frozen=True):
    """A single performance or quality target or published reference point."""

    metric: str
    kind: str  # "project_target" | "published"
    value: float
    comparison: str  # "lt" | "lte" | "gt" | "gte"
    source: str
    notes: str | None = None


# ---------------------------------------------------------------------------
# ComparisonRow
# ---------------------------------------------------------------------------


class ComparisonRow(msgspec.Struct, frozen=True):
    """One row in the baseline comparison table."""

    metric: str
    seerflow_value: float
    baseline_name: str
    baseline_value: float
    comparison: str
    delta: float
    verdict: str  # "pass" | "below" | "above" | "n/a"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class Projection(msgspec.Struct, frozen=True):
    """An estimated or measured performance projection."""

    kind: str  # e.g. "current" | "single_core" | "parallel" | "target"
    label: str
    eta_seconds: float | None
    note: str


# ---------------------------------------------------------------------------
# Report (top-level)
# ---------------------------------------------------------------------------


class Report(msgspec.Struct, frozen=True):
    """Complete LANL benchmark report, ready for serialisation."""

    accuracy: AccuracySummary
    telemetry: RunTelemetry
    host: HostInfo
    comparisons: tuple[ComparisonRow, ...]
    projections: tuple[Projection, ...]
    dataset_total_events: int
    first_attack_events: int
