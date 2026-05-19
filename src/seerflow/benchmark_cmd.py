"""``seerflow benchmark`` — surface the throughput harness + scorecard (S-307).

Wraps the read-only ``seerflow.launch.benchmark.run_benchmark`` seam (S-090)
and, for ``--scorecard``, the ``seerflow.lanl.validator.run_validation`` seam
(S-305). This module is the flat ``benchmark_cmd`` orchestrator and is
deliberately distinct from the ``seerflow.benchmark`` package owned by S-310
(the persisted ``benchmark-results.json`` artifact / CI gate live there).
"""
# ruff: noqa: T201 -- print() is the CLI output mechanism.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import msgspec.json

from seerflow.cli_format import format_table
from seerflow.validate_cmd import (
    EXIT_OK,
    EXIT_USAGE,
    _result_to_dict,
    _UsageError,
    _validate_dataset_dir,
)

if TYPE_CHECKING:
    import argparse

    from seerflow.lanl.validator import ValidationResult
    from seerflow.launch.benchmark import BenchmarkResult


def _benchmark_to_dict(result: BenchmarkResult, *, seed: int) -> dict[str, object]:
    """Deterministic machine-readable benchmark document."""
    return {
        "event_count": result.event_count,
        "elapsed_s": result.elapsed_s,
        "throughput_eps": result.throughput_eps,
        "latency_p50_ms": result.latency_p50_ms,
        "latency_p95_ms": result.latency_p95_ms,
        "latency_mean_ms": result.latency_mean_ms,
        "peak_rss_mb": result.peak_rss_mb,
        "stored_events": result.stored_events,
        "alerts": result.alerts,
        "seed": seed,
    }


def _emit_benchmark(doc: dict[str, object], *, as_json: bool) -> None:
    """Write ``doc`` to stdout as JSON or a human two-column table."""
    if as_json:
        sys.stdout.write(msgspec.json.encode(doc).decode() + "\n")
        return
    rows = [[k, str(doc[k])] for k in doc]
    print(format_table(["metric", "value"], rows))


def _render_scorecard(
    validation: ValidationResult,
    benchmark: BenchmarkResult,
    *,
    dataset_dir: str,
    seed: int,
) -> str:
    """One consolidated human table: Accuracy section + Performance section.

    ``seed`` is the benchmark RNG seed; it is kept in the Performance
    section so the scorecard is self-describing and reproducible.
    """
    acc = _result_to_dict(validation, dataset_dir=dataset_dir)
    acc_rows = [[k, str(acc[k])] for k in acc]
    perf = _benchmark_to_dict(benchmark, seed=seed)
    perf_rows = [[k, str(perf[k])] for k in perf]
    return "\n".join(
        (
            "## Seerflow Scorecard",
            "",
            "### Accuracy",
            format_table(["metric", "value"], acc_rows),
            "",
            "### Performance",
            format_table(["metric", "value"], perf_rows),
        )
    )


def _run_scorecard(args: argparse.Namespace) -> int:
    """Run both harnesses and print one consolidated table.

    ``--scorecard`` is human-readable by contract (FR-075 AC #3); it
    ignores ``--json``.
    """
    try:
        dataset = _validate_dataset_dir(args.dataset_dir)
    except _UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    from seerflow.lanl.validator import run_validation
    from seerflow.launch.benchmark import run_benchmark

    validation = run_validation(dataset)
    bench = run_benchmark(args.count, seed=args.seed)
    print(_render_scorecard(validation, bench, dataset_dir=str(dataset), seed=args.seed))
    return EXIT_OK


def run_benchmark_cmd(args: argparse.Namespace) -> int:
    """``seerflow benchmark`` entry point. Returns a process exit code."""
    if getattr(args, "scorecard", False):
        return _run_scorecard(args)
    from seerflow.launch.benchmark import run_benchmark

    bench = run_benchmark(args.count, seed=args.seed)
    _emit_benchmark(_benchmark_to_dict(bench, seed=args.seed), as_json=bool(args.json))
    return EXIT_OK


__all__ = ["run_benchmark_cmd"]
