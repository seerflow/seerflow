"""Real benchmark harness for the Seerflow pipeline (S-090).

Reuses the public pipeline API (the same one
``tests/benchmarks/profile_pipeline.py`` uses) -- no duplicate pipeline
wiring. Reports measured throughput, per-event latency (p50/p95/mean), and
peak RSS. Numbers are hardware-dependent: published values come from a real
local run, labelled "reproduce; your numbers will differ".
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from seerflow.config import load_config
from seerflow.correlation.holders import EngineHolder
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.launch.synthetic import build_events
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.pipeline.handler import make_handler
from seerflow.sigma.engine import SigmaEngine
from seerflow.storage.sqlite import SqliteBackend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from seerflow.receivers.base import RawEvent


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Immutable measured pipeline benchmark result."""

    event_count: int
    elapsed_s: float
    throughput_eps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    peak_rss_mb: float | None
    stored_events: int
    alerts: int


def _percentile(samples_ns: Sequence[float], q: int) -> float:
    """Return the ``q``-th percentile of ``samples_ns`` (0.0 if empty)."""
    if not samples_ns:
        return 0.0
    if len(samples_ns) == 1:
        return float(samples_ns[0])
    ordered = sorted(samples_ns)
    rank = (q / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _rss_kib_to_mb(kib: int) -> float:
    """Convert Linux ``ru_maxrss`` KiB to MB."""
    return kib / 1024.0


def _throughput(n: int, elapsed_s: float) -> float:
    """Events per second (0.0 when elapsed is non-positive)."""
    return n / elapsed_s if elapsed_s > 0 else 0.0


def _peak_rss_mb() -> float | None:
    """Peak RSS in MB, or ``None`` if ``resource`` is unavailable."""
    try:
        import resource
    except ImportError:  # pragma: no cover -- non-POSIX only
        return None
    return _rss_kib_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


async def _build_pipeline(data_dir: Path) -> tuple[SqliteBackend, object]:
    cfg_yaml = data_dir / "seerflow.yaml"
    cfg_yaml.write_text(
        "storage:\n"
        f"  data_dir: {data_dir}\n"
        "receivers:\n"
        "  syslog_enabled: false\n"
        "  otlp_grpc_enabled: false\n"
        "  otlp_http_enabled: false\n"
        "  webhook_enabled: false\n"
    )
    config = load_config(str(cfg_yaml))
    storage = await SqliteBackend.connect(config.storage)
    ensemble = DetectionEnsemble(config.detection)
    sigma = SigmaEngine()
    sigma.load_bundled()
    handler = make_handler(
        ensemble,
        storage,
        save_interval_ns=999_999_999_999,
        sigma_holder=EngineHolder(engine=sigma),
    )
    return storage, handler


async def _run(events: Sequence[RawEvent], data_dir: Path) -> BenchmarkResult:
    storage, handler = await _build_pipeline(data_dir)
    latencies_ms: list[float] = []
    try:
        start = time.perf_counter()
        for event in events:
            t0 = time.perf_counter_ns()
            await handler(event)  # type: ignore[operator]
            latencies_ms.append((time.perf_counter_ns() - t0) / 1_000_000.0)
        elapsed = time.perf_counter() - start
        await storage.flush()
        stored = (await storage.query_events(EventQuery(limit=1))).total
        alerts = (await storage.query_alerts(AlertQuery(limit=1))).total
    finally:
        await storage.close()
    n = len(events)
    return BenchmarkResult(
        event_count=n,
        elapsed_s=elapsed,
        throughput_eps=_throughput(n, elapsed),
        latency_p50_ms=_percentile(latencies_ms, 50),
        latency_p95_ms=_percentile(latencies_ms, 95),
        latency_mean_ms=statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        peak_rss_mb=_peak_rss_mb(),
        stored_events=stored,
        alerts=alerts,
    )


def run_benchmark(
    count: int, *, seed: int = 42, data_dir: Path | None = None
) -> BenchmarkResult:
    """Drive ``count`` synthetic events through a real pipeline and measure it."""
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")
    events = build_events(count, seed=seed)
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        return asyncio.run(_run(events, data_dir))
    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(_run(events, Path(tmp)))


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="seerflow.launch.benchmark",
        description="Measure Seerflow pipeline throughput / latency / memory.",
    )
    p.add_argument("--count", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument(
        "--markdown",
        action="store_true",
        help="Also print the rendered Markdown results report.",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    from datetime import date

    from seerflow.launch.report import render_benchmark_report

    args = _parse_args(sys.argv[1:] if argv is None else argv)
    result = run_benchmark(args.count, seed=args.seed, data_dir=args.data_dir)
    rss = "n/a" if result.peak_rss_mb is None else f"{result.peak_rss_mb:,.1f} MB"
    print(  # noqa: T201 -- CLI stdout is the contract
        f"events={result.event_count:,} "
        f"throughput={result.throughput_eps:,.0f} ev/s "
        f"p50={result.latency_p50_ms:.3f}ms p95={result.latency_p95_ms:.3f}ms "
        f"peak_rss={rss} alerts={result.alerts:,}"
    )
    if args.markdown:
        print(render_benchmark_report(result, date=date.today().isoformat()))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
