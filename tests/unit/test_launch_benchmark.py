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


def test_run_benchmark_uses_tempdir_when_no_data_dir() -> None:
    # data_dir omitted -> the TemporaryDirectory branch is exercised.
    result = run_benchmark(40, seed=3)
    assert result.event_count == 40
    assert result.stored_events == 40


def test_parse_args_defaults_and_overrides() -> None:
    from seerflow.launch.benchmark import _parse_args

    ns = _parse_args([])
    assert ns.count == 20_000
    assert ns.seed == 42
    assert ns.data_dir is None
    assert ns.markdown is False

    ns2 = _parse_args(["--count", "5", "--seed", "9", "--markdown"])
    assert ns2.count == 5
    assert ns2.seed == 9
    assert ns2.markdown is True


def test_main_prints_summary(capsys, tmp_path) -> None:
    from seerflow.launch.benchmark import main

    rc = main(["--count", "30", "--seed", "1", "--data-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "events=30" in out
    assert "throughput=" in out
    assert "p50=" in out


def test_main_markdown_emits_report(capsys, tmp_path) -> None:
    from seerflow.launch.benchmark import main

    rc = main(["--count", "30", "--seed", "1", "--data-dir", str(tmp_path), "--markdown"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Seerflow Benchmark Results" in out
    assert "python -m seerflow.launch.benchmark" in out


_FAKE = BenchmarkResult(
    event_count=42,
    elapsed_s=1.0,
    throughput_eps=42.0,
    latency_p50_ms=0.1,
    latency_p95_ms=0.2,
    latency_mean_ms=0.15,
    peak_rss_mb=12.5,
    stored_events=42,
    alerts=3,
)
_FAKE_NO_RSS = BenchmarkResult(
    event_count=7,
    elapsed_s=1.0,
    throughput_eps=7.0,
    latency_p50_ms=0.1,
    latency_p95_ms=0.2,
    latency_mean_ms=0.15,
    peak_rss_mb=None,
    stored_events=7,
    alerts=0,
)


def test_main_summary_deterministic(monkeypatch, capsys) -> None:
    # Stub run_benchmark so main()'s print/markdown lines are covered
    # deterministically without the heavy async pipeline (no asyncio
    # boundary -> coverage records the lines in any --cov scope).
    import seerflow.launch.benchmark as bench

    monkeypatch.setattr(bench, "run_benchmark", lambda *a, **k: _FAKE)
    rc = bench.main(["--count", "42"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "events=42" in out
    assert "peak_rss=12.5 MB" in out
    assert "alerts=3" in out


def test_main_summary_rss_na(monkeypatch, capsys) -> None:
    import seerflow.launch.benchmark as bench

    monkeypatch.setattr(bench, "run_benchmark", lambda *a, **k: _FAKE_NO_RSS)
    rc = bench.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "peak_rss=n/a" in out


def test_main_markdown_deterministic(monkeypatch, capsys) -> None:
    import seerflow.launch.benchmark as bench

    monkeypatch.setattr(bench, "run_benchmark", lambda *a, **k: _FAKE)
    rc = bench.main(["--markdown"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Seerflow Benchmark Results" in out
    assert "python -m seerflow.launch.benchmark" in out
