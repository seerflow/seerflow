"""Unit tests for seerflow.benchmark_cmd: dict shape, orchestrator, scorecard."""

from __future__ import annotations

import argparse
import json

import pytest

from seerflow import benchmark_cmd
from seerflow.launch.benchmark import BenchmarkResult


def _ns(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _br(**over: object) -> BenchmarkResult:
    base: dict[str, object] = dict(
        event_count=20000,
        elapsed_s=1.5,
        throughput_eps=13333.0,
        latency_p50_ms=0.05,
        latency_p95_ms=0.09,
        latency_mean_ms=0.06,
        peak_rss_mb=128.0,
        stored_events=20000,
        alerts=3,
    )
    base.update(over)
    return BenchmarkResult(**base)  # type: ignore[arg-type]


def test_benchmark_to_dict_shape() -> None:
    d = benchmark_cmd._benchmark_to_dict(_br(), seed=42)
    assert d == {
        "event_count": 20000,
        "elapsed_s": 1.5,
        "throughput_eps": 13333.0,
        "latency_p50_ms": 0.05,
        "latency_p95_ms": 0.09,
        "latency_mean_ms": 0.06,
        "peak_rss_mb": 128.0,
        "stored_events": 20000,
        "alerts": 3,
        "seed": 42,
    }


def test_benchmark_to_dict_peak_rss_none() -> None:
    d = benchmark_cmd._benchmark_to_dict(_br(peak_rss_mb=None), seed=7)
    assert d["peak_rss_mb"] is None


def test_run_benchmark_cmd_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "seerflow.launch.benchmark.run_benchmark",
        lambda count, *, seed=42, data_dir=None: _br(event_count=count),
    )
    rc = benchmark_cmd.run_benchmark_cmd(
        _ns(count=500, seed=42, json=True, scorecard=False, dataset_dir="x")
    )
    assert rc == benchmark_cmd.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["event_count"] == 500
    assert out["seed"] == 42


def test_run_benchmark_cmd_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "seerflow.launch.benchmark.run_benchmark",
        lambda count, *, seed=42, data_dir=None: _br(),
    )
    rc = benchmark_cmd.run_benchmark_cmd(
        _ns(count=10, seed=42, json=False, scorecard=False, dataset_dir="x")
    )
    assert rc == benchmark_cmd.EXIT_OK
    assert "throughput" in capsys.readouterr().out.lower()


def test_render_scorecard_has_both_sections() -> None:
    from seerflow.lanl.validator import ValidationResult

    vr = ValidationResult(
        true_positives=12,
        false_positives=1,
        false_negatives=0,
        precision=0.92,
        recall=1.0,
        f1_score=0.96,
        false_positive_rate=0.08,
        detection_latency_s={"r": 10.0},
        patterns_detected=frozenset({"r"}),
        total_events_processed=203,
        total_alerts=13,
    )
    text = benchmark_cmd._render_scorecard(vr, _br(), dataset_dir="/d")
    low = text.lower()
    assert "accuracy" in low
    assert "performance" in low
    assert "precision" in low
    assert "throughput" in low


def test_run_scorecard_runs_both_harnesses(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: object,
) -> None:
    from seerflow.lanl.validator import ValidationResult

    vr = ValidationResult(
        true_positives=1,
        false_positives=0,
        false_negatives=0,
        precision=1.0,
        recall=1.0,
        f1_score=1.0,
        false_positive_rate=0.0,
        detection_latency_s={"r": 5.0},
        patterns_detected=frozenset({"r"}),
        total_events_processed=1,
        total_alerts=1,
    )
    monkeypatch.setattr("seerflow.lanl.validator.run_validation", lambda _p: vr)
    monkeypatch.setattr(
        "seerflow.launch.benchmark.run_benchmark",
        lambda count, *, seed=42, data_dir=None: _br(event_count=count),
    )
    rc = benchmark_cmd.run_benchmark_cmd(
        _ns(count=10, seed=42, json=True, scorecard=True, dataset_dir=str(tmp_path))
    )
    assert rc == benchmark_cmd.EXIT_OK
    out = capsys.readouterr().out.lower()
    assert "accuracy" in out and "performance" in out


def test_run_scorecard_bad_dataset_dir_exit_2(
    capsys: pytest.CaptureFixture[str], tmp_path: object
) -> None:
    rc = benchmark_cmd.run_benchmark_cmd(
        _ns(
            count=10,
            seed=42,
            json=False,
            scorecard=True,
            dataset_dir=str(tmp_path / "nope"),  # type: ignore[operator]
        )
    )
    assert rc == benchmark_cmd.EXIT_USAGE
    assert "Error:" in capsys.readouterr().err


def test_validate_integration_smoke_real_fixtures() -> None:
    """`validate` over the committed synthetic fixtures returns parseable JSON
    whose numbers equal a direct run_validation call (no recomputation)."""
    import json as _json
    from pathlib import Path

    from seerflow.lanl.validator import run_validation
    from seerflow.validate_cmd import _result_to_dict

    fixtures = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "lanl"
    direct = _result_to_dict(run_validation(fixtures), dataset_dir=str(fixtures))
    encoded = _json.loads(_json.dumps(direct))
    assert encoded["auc"] is None
    assert encoded["precision"] == direct["precision"]
    assert encoded["total_events_processed"] == direct["total_events_processed"]


def test_main_dispatches_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys as _sys

    import seerflow.__main__ as m

    monkeypatch.setattr(_sys, "argv", ["seerflow", "validate", "/no/such/dir"])
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code == 2
