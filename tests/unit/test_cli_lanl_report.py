"""Unit tests for ``seerflow lanl-report`` CLI subcommand (S-358, slice 4).

Tests are written BEFORE implementation (TDD: RED phase).

Coverage:
- Argument parsing (positional report_json, --json flag).
- Table output: exit 0, header present.
- JSON output: exit 0, json.loads succeeds, expected top-level keys.
- Missing file: non-zero exit, clear error message to stderr.
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.cli import parse_args
from seerflow.lanl.report.io import write_report_json
from seerflow.lanl.report.schema import (
    AccuracySummary,
    HostInfo,
    RunTelemetry,
    ScenarioSummary,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_accuracy() -> AccuracySummary:
    return AccuracySummary(
        precision=0.85,
        recall=0.90,
        f1=0.875,
        auc=0.80,
        false_positive_rate=0.05,
        true_positives=18,
        false_positives=3,
        false_negatives=2,
        total_alerts=21,
        patterns_detected=("brute-force",),
        scenarios=(
            ScenarioSummary(
                name="brute-force-lateral-movement",
                detected=True,
                mttd_seconds=60.0,
                missed_record_count=0,
            ),
        ),
        missed_attributions=(),
    )


def _make_telemetry() -> RunTelemetry:
    return RunTelemetry(
        wall_s=42.5,
        events_processed=3000,
        throughput_eps=70.5,
        mean_latency_s=0.000014,
        peak_rss_mb=128.0,
    )


def _make_host() -> HostInfo:
    return HostInfo(
        cpu_model="Intel(R) Core(TM) i7-9750H",
        physical_cores=6,
        logical_cores=12,
        ram_gb=16.0,
        platform="Linux-6.1.0-amd64-x86_64",
    )


# ---------------------------------------------------------------------------
# Parser surface tests
# ---------------------------------------------------------------------------


class TestLanlReportParserArgs:
    """Verify the ``lanl-report`` subcommand is registered and its flags work."""

    def test_parses_positional_report_json(self, tmp_path: Path) -> None:
        report_path = str(tmp_path / "report.json")
        ns = parse_args(["lanl-report", report_path])
        assert ns.command == "lanl-report"
        assert ns.report_json == report_path

    def test_json_flag_defaults_false(self, tmp_path: Path) -> None:
        report_path = str(tmp_path / "report.json")
        ns = parse_args(["lanl-report", report_path])
        assert ns.json is False

    def test_json_flag_true_when_passed(self, tmp_path: Path) -> None:
        report_path = str(tmp_path / "report.json")
        ns = parse_args(["lanl-report", report_path, "--json"])
        assert ns.json is True

    def test_missing_positional_exits_with_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["lanl-report"])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Functional tests (via __main__.main() + capsys)
# ---------------------------------------------------------------------------


class TestLanlReportTableOutput:
    """Table mode (default): exit 0, header present in stdout."""

    def test_table_exit_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=False)
        rc = run_lanl_report(ns)
        assert rc == 0

    def test_table_contains_behavior_header(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=False)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        assert "Behavior" in captured.out

    def test_table_contains_precision_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=False)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        assert "precision" in captured.out
        assert "0.8500" in captured.out


class TestLanlReportJsonOutput:
    """JSON mode (--json): exit 0, stdout is valid JSON with expected keys."""

    def test_json_exit_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=True)
        rc = run_lanl_report(ns)
        assert rc == 0

    def test_json_stdout_is_valid_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=True)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict)

    def test_json_has_expected_top_level_keys(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=True)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        for key in ("accuracy", "telemetry", "host", "comparisons", "projections"):
            assert key in parsed, f"missing key: {key!r}"

    def test_json_accuracy_precision_round_trips(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(report_path), json=True)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert abs(parsed["accuracy"]["precision"] - 0.85) < 1e-6


class TestLanlReportMissingFile:
    """Missing / non-existent path: non-zero exit, clear error to stderr."""

    def test_missing_file_returns_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(tmp_path / "does_not_exist.json"), json=False)
        rc = run_lanl_report(ns)
        assert rc != 0

    def test_missing_file_message_to_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from seerflow.lanl.report_cmd import run_lanl_report

        ns = argparse.Namespace(report_json=str(tmp_path / "does_not_exist.json"), json=False)
        run_lanl_report(ns)
        captured = capsys.readouterr()
        assert "does_not_exist.json" in captured.err or "not found" in captured.err.lower()


class TestLanlReportMainDispatch:
    """``seerflow.__main__.main()`` dispatches ``lanl-report`` to run_lanl_report."""

    def test_main_dispatches_lanl_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report_path = tmp_path / "report.json"
        write_report_json(report_path, _make_accuracy(), _make_telemetry(), _make_host())

        from seerflow.__main__ import main

        mock_args = argparse.Namespace(
            config=None,
            command="lanl-report",
            report_json=str(report_path),
            json=False,
        )
        with (
            patch("seerflow.__main__.parse_args", return_value=mock_args),
            patch("seerflow.__main__._run_async_int") as _mock_async,
            patch("seerflow.lanl.report_cmd.run_lanl_report", return_value=0) as mock_cmd,
        ):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            mock_cmd.assert_called_once_with(mock_args)
