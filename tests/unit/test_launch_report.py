"""Unit tests for the pure benchmark report renderer (S-090)."""

from __future__ import annotations

from seerflow.launch.benchmark import BenchmarkResult
from seerflow.launch.report import render_benchmark_report

_R = BenchmarkResult(
    event_count=20_000,
    elapsed_s=10.0,
    throughput_eps=2000.0,
    latency_p50_ms=0.4,
    latency_p95_ms=0.9,
    latency_mean_ms=0.5,
    peak_rss_mb=128.5,
    stored_events=20_000,
    alerts=12,
)


def test_render_is_deterministic() -> None:
    a = render_benchmark_report(_R, date="2026-05-16")
    b = render_benchmark_report(_R, date="2026-05-16")
    assert a == b


def test_render_contains_throughput_and_latency() -> None:
    out = render_benchmark_report(_R, date="2026-05-16")
    assert "2,000" in out
    assert "0.400" in out  # p50 ms
    assert "0.900" in out  # p95 ms


def test_render_contains_reproduce_command() -> None:
    out = render_benchmark_report(_R, date="2026-05-16")
    assert "python -m seerflow.launch.benchmark" in out


def test_render_contains_hardware_caveat() -> None:
    out = render_benchmark_report(_R, date="2026-05-16").lower()
    assert "hardware" in out or "your numbers will differ" in out


def test_render_links_s088_validation() -> None:
    out = render_benchmark_report(_R, date="2026-05-16")
    assert "Validation" in out
    assert "lanl.report" in out


def test_render_rss_na_when_none() -> None:
    r = BenchmarkResult(
        event_count=1,
        elapsed_s=1.0,
        throughput_eps=1.0,
        latency_p50_ms=0.1,
        latency_p95_ms=0.2,
        latency_mean_ms=0.15,
        peak_rss_mb=None,
        stored_events=1,
        alerts=0,
    )
    assert "n/a" in render_benchmark_report(r, date="2026-05-16")
