"""Pure report builder for the LANL benchmark (S-358, slice 2).

``build_report`` assembles a complete :class:`~seerflow.lanl.report.schema.Report`
from its constituent parts.  It is a **pure function** — no I/O, no calls to
``detect_host``.  Hardware detection is the caller's responsibility.
"""

from __future__ import annotations

from seerflow.lanl.report.hardware import project
from seerflow.lanl.report.schema import (
    FIRST_ATTACK_EVENTS,
    TOTAL_EVENTS,
    AccuracySummary,
    Baseline,
    ComparisonRow,
    HostInfo,
    Report,
    RunTelemetry,
)

# ---------------------------------------------------------------------------
# Verdict helpers
# ---------------------------------------------------------------------------

_VERDICT_FAIL_ABOVE = frozenset({"lte", "lt"})
_VERDICT_FAIL_BELOW = frozenset({"gte", "gt"})


def _evaluate_verdict(
    seerflow_value: float,
    baseline_value: float,
    comparison: str,
) -> str:
    """Return ``"pass"``, ``"below"``, or ``"above"`` for a comparison.

    The *comparison* string describes the condition that seerflow **must**
    satisfy to pass: e.g. ``"gte"`` means ``seerflow_value >= baseline_value``.

    Args:
        seerflow_value: The measured seerflow metric value.
        baseline_value: The reference/target value.
        comparison:     One of ``"lt"``, ``"lte"``, ``"gt"``, ``"gte"``.

    Returns:
        ``"pass"`` if the condition holds, ``"below"`` if seerflow is too low
        (failing a ``gte``/``gt`` check), or ``"above"`` if seerflow is too
        high (failing a ``lte``/``lt`` check).
    """
    if comparison == "gte":
        return "pass" if seerflow_value >= baseline_value else "below"
    if comparison == "gt":
        return "pass" if seerflow_value > baseline_value else "below"
    if comparison == "lte":
        return "pass" if seerflow_value <= baseline_value else "above"
    if comparison == "lt":
        return "pass" if seerflow_value < baseline_value else "above"
    return "n/a"


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------


def build_report(
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    baselines: list[Baseline],
    host: HostInfo,
    *,
    total_events: int = TOTAL_EVENTS,
    first_attack_events: int = FIRST_ATTACK_EVENTS,
) -> Report:
    """Assemble a complete :class:`~seerflow.lanl.report.schema.Report`.

    This function is **pure** — it performs no I/O and does not call
    :func:`~seerflow.lanl.report.hardware.detect_host`.

    Comparison rows are built from *baselines* by mapping each
    ``baseline.metric`` to the corresponding :class:`AccuracySummary`
    attribute.  Baselines whose metric does not map to an attribute on
    :class:`AccuracySummary` are silently skipped.

    Args:
        accuracy:             Accuracy metrics from the validation run.
        telemetry:            Wall-clock and throughput metrics.
        baselines:            List of reference targets / published values.
        host:                 Hardware metadata for the benchmarked machine.
        total_events:         Override for the dataset size constant.
        first_attack_events:  Override for the attack-subset size constant.

    Returns:
        A frozen, serialisable :class:`~seerflow.lanl.report.schema.Report`.
    """
    comparison_rows: list[ComparisonRow] = []

    for baseline in baselines:
        if not hasattr(accuracy, baseline.metric):
            continue

        seerflow_value = float(getattr(accuracy, baseline.metric))
        baseline_value = baseline.value
        delta = seerflow_value - baseline_value
        verdict = _evaluate_verdict(seerflow_value, baseline_value, baseline.comparison)

        comparison_rows.append(
            ComparisonRow(
                metric=baseline.metric,
                seerflow_value=seerflow_value,
                baseline_name=baseline.source,
                baseline_value=baseline_value,
                comparison=baseline.comparison,
                delta=delta,
                verdict=verdict,
            )
        )

    projections = project(telemetry.throughput_eps, total_events, host)

    return Report(
        accuracy=accuracy,
        telemetry=telemetry,
        host=host,
        comparisons=tuple(comparison_rows),
        projections=tuple(projections),
        dataset_total_events=total_events,
        first_attack_events=first_attack_events,
    )
