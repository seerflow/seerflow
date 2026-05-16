"""Unit tests for the launch benchmark harness (S-090)."""

from __future__ import annotations

import pytest

from seerflow.launch.benchmark import (
    BenchmarkResult,
    _percentile,
    _rss_kib_to_mb,
    _throughput,
    run_benchmark,
)


def test_percentile_p50() -> None:
    assert _percentile([10.0, 20.0, 30.0, 40.0], 50) == pytest.approx(25.0, abs=5.0)


def test_percentile_p95() -> None:
    samples = [float(x) for x in range(1, 101)]
    assert _percentile(samples, 95) >= 90.0


def test_percentile_single_sample() -> None:
    assert _percentile([7.0], 95) == 7.0


def test_percentile_empty_is_zero() -> None:
    assert _percentile([], 50) == 0.0


def test_rss_kib_to_mb() -> None:
    assert _rss_kib_to_mb(2048) == pytest.approx(2.0)


def test_throughput_basic() -> None:
    assert _throughput(1000, 2.0) == pytest.approx(500.0)


def test_throughput_zero_elapsed_is_zero() -> None:
    assert _throughput(1000, 0.0) == 0.0


def test_run_benchmark_small(tmp_path) -> None:
    result = run_benchmark(60, seed=7, data_dir=tmp_path)
    assert isinstance(result, BenchmarkResult)
    assert result.event_count == 60
    assert result.stored_events == 60
    assert result.elapsed_s > 0.0
    assert result.throughput_eps > 0.0
    assert result.latency_p50_ms >= 0.0
    assert result.latency_p95_ms >= result.latency_p50_ms
    assert result.alerts >= 0


def test_run_benchmark_rejects_nonpositive() -> None:
    with pytest.raises(ValueError, match="count"):
        run_benchmark(0)
