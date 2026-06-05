"""Unit tests for seerflow.lanl.report.render (S-358, slice 3).

Tests cover render_table and render_json.  Written FIRST (TDD — RED phase).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec
import pytest

from seerflow.lanl.report.schema import (
    AccuracySummary,
    ComparisonRow,
    HostInfo,
    Projection,
    Report,
    RunTelemetry,
    ScenarioSummary,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Fixtures (delegate to the shared factories in tests/unit/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def accuracy(make_accuracy: Callable[..., AccuracySummary]) -> AccuracySummary:
    return make_accuracy(
        precision=0.92,
        recall=0.88,
        f1=0.899,
        auc=0.95,
        false_positive_rate=0.04,
        true_positives=110,
        false_positives=10,
        false_negatives=15,
        total_alerts=120,
        patterns_detected=("brute-force", "lateral-movement"),
        scenarios=(
            ScenarioSummary(
                name="scenario-alpha",
                detected=True,
                mttd_seconds=42.5,
                missed_record_count=0,
            ),
            ScenarioSummary(
                name="scenario-beta",
                detected=False,
                mttd_seconds=None,
                missed_record_count=3,
            ),
        ),
        missed_attributions=("record-A", "record-B"),
    )


@pytest.fixture()
def telemetry(make_telemetry: Callable[..., RunTelemetry]) -> RunTelemetry:
    return make_telemetry(
        wall_s=300.0,
        events_processed=1_000_000,
        throughput_eps=3333.33,
        mean_latency_s=0.003,
        peak_rss_mb=512.0,
    )


@pytest.fixture()
def host(make_host: Callable[..., HostInfo]) -> HostInfo:
    return make_host(
        cpu_model="Intel Core i7-9750H",
        physical_cores=6,
        logical_cores=12,
        ram_gb=32.0,
        platform="Linux-5.15",
    )


@pytest.fixture()
def comparisons() -> tuple[ComparisonRow, ...]:
    return (
        ComparisonRow(
            metric="precision",
            seerflow_value=0.92,
            baseline_name="Seerflow target v1",
            baseline_value=0.90,
            comparison="gte",
            delta=0.02,
            verdict="pass",
        ),
        ComparisonRow(
            metric="recall",
            seerflow_value=0.88,
            baseline_name="Published LogBERT",
            baseline_value=0.91,
            comparison="gte",
            delta=-0.03,
            verdict="below",
        ),
    )


@pytest.fixture()
def projections() -> tuple[Projection, ...]:
    return (
        Projection(
            kind="current",
            label="full-run ETA at current rate",
            eta_seconds=482238.0,
            note="measured ~3,333 eps",
        ),
        Projection(
            kind="caveat",
            label="single-threaded today",
            eta_seconds=None,
            note="more cores give ZERO speedup until S-356 parallelization lands",
        ),
    )


@pytest.fixture()
def full_report(
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
    comparisons: tuple[ComparisonRow, ...],
    projections: tuple[Projection, ...],
) -> Report:
    return Report(
        accuracy=accuracy,
        telemetry=telemetry,
        host=host,
        comparisons=comparisons,
        projections=projections,
        dataset_total_events=1_607_452_967,
        first_attack_events=58_655_985,
    )


@pytest.fixture()
def empty_comparisons_report(
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
    projections: tuple[Projection, ...],
) -> Report:
    return Report(
        accuracy=accuracy,
        telemetry=telemetry,
        host=host,
        comparisons=(),
        projections=projections,
        dataset_total_events=1_607_452_967,
        first_attack_events=58_655_985,
    )


# ---------------------------------------------------------------------------
# render_table tests
# ---------------------------------------------------------------------------


def test_render_table_returns_nonempty_string(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_table_contains_behavior_section_header(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "Behavior" in result or "BEHAVIOR" in result or "behavior" in result


def test_render_table_contains_known_metric_value(full_report: Report) -> None:
    """precision=0.92 or recall=0.88 must appear in the output."""
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "0.92" in result or "0.88" in result


def test_render_table_contains_scenario_name(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "scenario-alpha" in result


def test_render_table_contains_caveat_marker(full_report: Report) -> None:
    """The caveat projection must be visually prominent (!! prefix)."""
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "!!" in result


def test_render_table_contains_baseline_source(full_report: Report) -> None:
    """Baseline source name must appear in the comparison section."""
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "Seerflow target v1" in result or "Published LogBERT" in result


def test_render_table_contains_comparison_section_header(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    lower = result.lower()
    assert "comparison" in lower or "baseline" in lower


def test_render_table_contains_efficiency_section(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    lower = result.lower()
    assert "efficiency" in lower or "throughput" in lower or "host" in lower


def test_render_table_contains_projection_section(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    lower = result.lower()
    assert "projection" in lower or "hardware" in lower


def test_render_table_empty_comparisons_shows_no_baseline_message(
    empty_comparisons_report: Report,
) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(empty_comparisons_report)
    lower = result.lower()
    assert "no comparable baselines" in lower or "no attacks" in lower


def test_render_table_contains_host_cpu_model(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    assert "Intel Core i7-9750H" in result


def test_render_table_contains_missed_attributions_count(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_table

    result = render_table(full_report)
    # 2 missed attributions
    assert "2" in result


# ---------------------------------------------------------------------------
# render_json tests
# ---------------------------------------------------------------------------


def test_render_json_returns_dict(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    assert isinstance(result, dict)


def test_render_json_round_trips_through_msgspec(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    # Must not raise
    encoded = msgspec.json.encode(result)
    assert len(encoded) > 0


def test_render_json_contains_accuracy_key(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    assert "accuracy" in result


def test_render_json_contains_projections_key(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    assert "projections" in result


def test_render_json_nested_accuracy_has_precision(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    accuracy_dict = result["accuracy"]
    assert isinstance(accuracy_dict, dict)
    assert "precision" in accuracy_dict


def test_render_json_projections_is_list(full_report: Report) -> None:
    from seerflow.lanl.report.render import render_json

    result = render_json(full_report)
    assert isinstance(result["projections"], list)
