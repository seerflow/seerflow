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
