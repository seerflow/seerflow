"""Unit tests for seerflow.lanl.report.io (S-358, slice 3).

Tests cover write_report_json / load_report_inputs round-trips.
Written FIRST (TDD — RED phase).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.lanl.report.schema import (
    AccuracySummary,
    HostInfo,
    RunTelemetry,
    ScenarioSummary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def accuracy() -> AccuracySummary:
    return AccuracySummary(
        precision=0.87,
        recall=0.80,
        f1=0.833,
        auc=0.91,
        false_positive_rate=0.06,
        true_positives=80,
        false_positives=12,
        false_negatives=20,
        total_alerts=92,
        patterns_detected=("ssh-bruteforce",),
        scenarios=(
            ScenarioSummary(
                name="scenario-one",
                detected=True,
                mttd_seconds=15.0,
                missed_record_count=1,
            ),
        ),
        missed_attributions=("rec-X",),
    )


@pytest.fixture()
def telemetry() -> RunTelemetry:
    return RunTelemetry(
        wall_s=120.5,
        events_processed=500_000,
        throughput_eps=4150.0,
        mean_latency_s=0.0024,
        peak_rss_mb=256.0,
    )


@pytest.fixture()
def host() -> HostInfo:
    return HostInfo(
        cpu_model="AMD Ryzen 5 3600",
        physical_cores=6,
        logical_cores=12,
        ram_gb=16.0,
        platform="Linux-5.4",
    )


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


def test_write_and_load_round_trip(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    """write_report_json → load_report_inputs must reproduce all fields exactly."""
    from seerflow.lanl.report.io import ReportInputs, load_report_inputs, write_report_json

    dest = tmp_path / "report.json"
    write_report_json(dest, accuracy, telemetry, host)

    assert dest.exists(), "JSON file was not created"

    loaded = load_report_inputs(dest)

    assert isinstance(loaded, ReportInputs)
    assert loaded.accuracy == accuracy
    assert loaded.telemetry == telemetry
    assert loaded.host == host


def test_written_file_is_valid_json(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    """Output file must be parseable JSON (pretty-printed bytes)."""
    import json

    from seerflow.lanl.report.io import write_report_json

    dest = tmp_path / "report.json"
    write_report_json(dest, accuracy, telemetry, host)

    raw = dest.read_bytes()
    # Should not raise
    parsed = json.loads(raw)
    assert "accuracy" in parsed


def test_write_creates_parent_directories(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    """Parent directories must be created automatically."""
    from seerflow.lanl.report.io import load_report_inputs, write_report_json

    dest = tmp_path / "sub" / "nested" / "report.json"
    assert not dest.parent.exists(), "precondition: parent does not exist"

    write_report_json(dest, accuracy, telemetry, host)

    assert dest.exists()
    loaded = load_report_inputs(dest)
    assert loaded.accuracy == accuracy


def test_load_report_inputs_returns_report_inputs_type(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    from seerflow.lanl.report.io import ReportInputs, load_report_inputs, write_report_json

    dest = tmp_path / "r.json"
    write_report_json(dest, accuracy, telemetry, host)
    loaded = load_report_inputs(dest)
    assert type(loaded).__name__ == "ReportInputs"
    assert isinstance(loaded, ReportInputs)


def test_report_inputs_fields_match_accuracy_precision(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    from seerflow.lanl.report.io import load_report_inputs, write_report_json

    dest = tmp_path / "report.json"
    write_report_json(dest, accuracy, telemetry, host)
    loaded = load_report_inputs(dest)
    assert loaded.accuracy.precision == pytest.approx(accuracy.precision)


def test_report_inputs_telemetry_wall_s_preserved(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    from seerflow.lanl.report.io import load_report_inputs, write_report_json

    dest = tmp_path / "report.json"
    write_report_json(dest, accuracy, telemetry, host)
    loaded = load_report_inputs(dest)
    assert loaded.telemetry.wall_s == pytest.approx(telemetry.wall_s)


def test_report_inputs_host_cpu_model_preserved(
    tmp_path: Path,
    accuracy: AccuracySummary,
    telemetry: RunTelemetry,
    host: HostInfo,
) -> None:
    from seerflow.lanl.report.io import load_report_inputs, write_report_json

    dest = tmp_path / "report.json"
    write_report_json(dest, accuracy, telemetry, host)
    loaded = load_report_inputs(dest)
    assert loaded.host.cpu_model == host.cpu_model
