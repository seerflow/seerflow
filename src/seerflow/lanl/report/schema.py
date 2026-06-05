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

from typing import Literal, Protocol, runtime_checkable

import msgspec

# ---------------------------------------------------------------------------
# Dataset constants (full LANL Unified Host and Network Dataset v2)
# ---------------------------------------------------------------------------

TOTAL_EVENTS: int = 1_607_452_967
FIRST_ATTACK_EVENTS: int = 58_655_985

# ---------------------------------------------------------------------------
# Literal discriminants — single source of truth for known field values.
# ``baselines.py`` derives its known-value frozensets from these via
# ``typing.get_args`` so there is exactly one place to edit.
# ---------------------------------------------------------------------------

BaselineKind = Literal["project_target", "published"]
Comparison = Literal["lt", "lte", "gt", "gte"]
Verdict = Literal["pass", "below", "above", "n/a"]


# ---------------------------------------------------------------------------
# Structural Protocols for ``AccuracySummary.from_validation_result``
# ---------------------------------------------------------------------------


@runtime_checkable
class ScenarioLike(Protocol):
    """Structural shape of a ``ValidationResult`` attack scenario."""

    name: str
    detected: bool
    mttd_seconds: float | None
    missed_record_count: int


@runtime_checkable
class MissedAttributionLike(Protocol):
    """Structural shape of a ``ValidationResult`` missed attribution."""

    record_repr: str


@runtime_checkable
class ValidationResultLike(Protocol):
    """Structural shape consumed by :meth:`AccuracySummary.from_validation_result`.

    Both :class:`~seerflow.lanl.validator.ValidationResult` and
    :class:`~seerflow.lanl.streaming.StreamingValidationResult` satisfy this
    Protocol (the latter delegates attribute access via ``__getattr__``), as do
    the ``SimpleNamespace`` fakes used in the unit tests.
    """

    precision: float
    recall: float
    f1_score: float
    auc: float | None
    false_positive_rate: float
    true_positives: int
    false_positives: int
    false_negatives: int
    total_alerts: int
    patterns_detected: frozenset[str]
    attack_scenarios: tuple[ScenarioLike, ...]
    missed_attributions: tuple[MissedAttributionLike, ...]


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
    def from_validation_result(cls, result: ValidationResultLike) -> AccuracySummary:
        """Map a :class:`~seerflow.lanl.validator.ValidationResult` (or a
        :class:`~seerflow.lanl.streaming.StreamingValidationResult`, which
        delegates attribute access via ``__getattr__``) to an
        :class:`AccuracySummary`.

        *result* is annotated with the structural :class:`ValidationResultLike`
        Protocol so mypy type-checks the field mapping. The ``getattr``
        defensive defaults are retained because the real results and the
        ``SimpleNamespace`` test fakes may omit optional attributes.

        Tolerates:
        - ``auc`` being ``None`` → normalised to ``0.0``.
        - ``f1_score`` attribute name → mapped to ``f1``.
        - ``patterns_detected`` being a :class:`frozenset` → sorted tuple.
        - ``attack_scenarios`` entries having ``name / detected / mttd_seconds /
          missed_record_count`` attributes.
        - ``missed_attributions`` entries with a ``record_repr`` attribute or
          being plain strings.
        """
        raw_auc = getattr(result, "auc", None)
        auc: float = 0.0 if raw_auc is None else float(raw_auc)

        raw_patterns = getattr(result, "patterns_detected", None) or frozenset()
        patterns: tuple[str, ...] = tuple(sorted(raw_patterns))

        raw_scenarios = getattr(result, "attack_scenarios", None) or ()
        scenarios: tuple[ScenarioSummary, ...] = tuple(
            ScenarioSummary(
                name=str(getattr(sc, "name", "")),
                detected=bool(getattr(sc, "detected", False)),
                mttd_seconds=getattr(sc, "mttd_seconds", None),
                missed_record_count=int(getattr(sc, "missed_record_count", 0)),
            )
            for sc in raw_scenarios
        )

        raw_attrs = getattr(result, "missed_attributions", None) or ()
        missed_attributions: tuple[str, ...] = tuple(
            getattr(ma, "record_repr", str(ma)) for ma in raw_attrs
        )

        return cls(
            precision=float(getattr(result, "precision", 0.0)),
            recall=float(getattr(result, "recall", 0.0)),
            f1=float(getattr(result, "f1_score", 0.0)),
            auc=auc,
            false_positive_rate=float(getattr(result, "false_positive_rate", 0.0)),
            true_positives=int(getattr(result, "true_positives", 0)),
            false_positives=int(getattr(result, "false_positives", 0)),
            false_negatives=int(getattr(result, "false_negatives", 0)),
            total_alerts=int(getattr(result, "total_alerts", 0)),
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
    kind: BaselineKind
    value: float
    comparison: Comparison
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
    comparison: Comparison
    delta: float
    verdict: Verdict


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
