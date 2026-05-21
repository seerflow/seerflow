"""Benchmark scorecard artifact + regression gate (S-310 / FR-078 / NFR-016).

Fuses S-305's honest accuracy metrics (``lanl.validator.run_validation``)
with the real pipeline's throughput/latency/RSS
(``launch.benchmark.run_benchmark``) into a deterministic, git-SHA-stamped
scorecard, writes the append-only ``benchmark-results.json`` artifact, and
gates CI on a >5 % relative regression versus a committed baseline.

Design: ``git_sha`` and ``timestamp`` are injected into the pure builder
(never ``datetime.now()`` inside the core) so unit output is deterministic
-- mirrors ``seerflow.lanl.report``'s injected ``date``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - only a fixed-argv `git rev-parse`; see resolve_git_sha
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from pathlib import Path

    from seerflow.lanl.validator import ValidationResult
    from seerflow.launch.benchmark import BenchmarkResult

# Heterogeneous JSON object (scorecard dicts mix str/float/int/nested maps).
# ``TypeAlias`` (not PEP 695 ``type``) keeps the 3.11 floor (project NFR).
JsonDict: TypeAlias = "dict[str, object]"

SCHEMA_VERSION = 1
# NFR-016: regression iff relative drop is strictly greater than 5 %.
REGRESSION_THRESHOLD = 0.05
# Floating-point slack so a *clean* 5.0 % drop (e.g. 1.0 -> 0.95, which is
# 0.050000000000000044 in IEEE-754) is treated as the boundary, not a
# regression. Far smaller than any meaningful detection delta.
_REGRESSION_EPSILON = 1e-9
# Gated metrics (NFR-016). RSS is recorded but not gated.
_GATED = ("precision", "recall", "f1_score", "throughput_eps")
# Synthetic-subset benchmark size: small => fast CI, still a real pipeline.
DEFAULT_BENCHMARK_EVENTS = 2000


@dataclass(frozen=True, slots=True)
class Scorecard:
    """Immutable fused accuracy + performance scorecard."""

    git_sha: str
    timestamp: str
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float
    true_positives: int
    false_positives: int
    false_negatives: int
    total_events_processed: int
    total_alerts: int
    scope_label: str
    per_family: dict[str, dict[str, float | int]]
    throughput_eps: float
    latency_p50_ms: float
    latency_p95_ms: float
    peak_rss_mb: float | None
    benchmark_event_count: int


@dataclass(frozen=True, slots=True)
class GateResult:
    """Result of the NFR-016 regression evaluation."""

    passed: bool
    failures: list[str]


def build_scorecard(
    validation: ValidationResult,
    benchmark: BenchmarkResult,
    *,
    git_sha: str,
    timestamp: str,
) -> Scorecard:
    """Fuse honest accuracy + measured performance into a Scorecard.

    Pure: ``git_sha`` and ``timestamp`` are injected by the caller so the
    output is deterministic and unit-testable.
    """
    per_family: dict[str, dict[str, float | int]] = {
        name: {
            "precision": fm.precision,
            "recall": fm.recall,
            "f1_score": fm.f1_score,
            "true_positives": fm.true_positives,
            "false_positives": fm.false_positives,
            "false_negatives": fm.false_negatives,
            "total_alerts": fm.total_alerts,
        }
        for name, fm in sorted(validation.per_family.items())
    }
    return Scorecard(
        git_sha=git_sha,
        timestamp=timestamp,
        precision=validation.precision,
        recall=validation.recall,
        f1_score=validation.f1_score,
        false_positive_rate=validation.false_positive_rate,
        true_positives=validation.true_positives,
        false_positives=validation.false_positives,
        false_negatives=validation.false_negatives,
        total_events_processed=validation.total_events_processed,
        total_alerts=validation.total_alerts,
        scope_label=validation.scope_label,
        per_family=per_family,
        throughput_eps=benchmark.throughput_eps,
        latency_p50_ms=benchmark.latency_p50_ms,
        latency_p95_ms=benchmark.latency_p95_ms,
        peak_rss_mb=benchmark.peak_rss_mb,
        benchmark_event_count=benchmark.event_count,
    )


def scorecard_to_dict(sc: Scorecard) -> JsonDict:
    """Serialize a Scorecard to a stable, deterministic dict."""
    return {
        "schema_version": SCHEMA_VERSION,
        "git_sha": sc.git_sha,
        "timestamp": sc.timestamp,
        "accuracy": {
            "precision": sc.precision,
            "recall": sc.recall,
            "f1_score": sc.f1_score,
            "false_positive_rate": sc.false_positive_rate,
            "true_positives": sc.true_positives,
            "false_positives": sc.false_positives,
            "false_negatives": sc.false_negatives,
            "total_events_processed": sc.total_events_processed,
            "total_alerts": sc.total_alerts,
            "scope_label": sc.scope_label,
            "per_family": sc.per_family,
        },
        "performance": {
            "throughput_eps": sc.throughput_eps,
            "latency_p50_ms": sc.latency_p50_ms,
            "latency_p95_ms": sc.latency_p95_ms,
            "peak_rss_mb": sc.peak_rss_mb,
            "benchmark_event_count": sc.benchmark_event_count,
        },
    }


def _section(d: JsonDict, key: str) -> JsonDict:
    """Return a nested object section, narrowed to ``JsonDict`` for mypy."""
    value = d[key]
    if not isinstance(value, dict):
        msg = f"scorecard section {key!r} is not an object"
        raise TypeError(msg)
    return value


def _summary(d: JsonDict) -> JsonDict:
    acc = _section(d, "accuracy")
    perf = _section(d, "performance")
    return {
        "git_sha": d["git_sha"],
        "timestamp": d["timestamp"],
        "accuracy_summary": {
            "precision": acc["precision"],
            "recall": acc["recall"],
            "f1_score": acc["f1_score"],
        },
        "performance_summary": {"throughput_eps": perf["throughput_eps"]},
    }


def append_history(new_dict: JsonDict, existing_path: Path) -> JsonDict:
    """Return ``new_dict`` with an append-only ``history`` array.

    Prior runs (the previous top-level entry plus its own history) are
    carried forward. A missing or corrupt existing file yields an empty
    history (fail-open: a fresh artifact must still be writable).
    """
    history: list[JsonDict] = []
    if existing_path.exists():
        try:
            prev = json.loads(existing_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = None
        if isinstance(prev, dict):
            prior = prev.get("history", [])
            if isinstance(prior, list):
                history = list(prior)
            if "git_sha" in prev and "accuracy" in prev:
                history.append(_summary(prev))
    return {**new_dict, "history": history}


def _metric(card: JsonDict, name: str) -> float:
    if name == "throughput_eps":
        return float(_section(card, "performance")["throughput_eps"])  # type: ignore[arg-type]
    return float(_section(card, "accuracy")[name])  # type: ignore[arg-type]


def evaluate_regression(candidate: JsonDict, baseline: JsonDict) -> GateResult:
    """Apply the NFR-016 rule to precision/recall/F1/throughput.

    A metric regresses iff ``baseline > 0`` and the relative drop
    ``(baseline - candidate) / baseline`` is *strictly greater* than
    ``REGRESSION_THRESHOLD`` (5 %). RSS is recorded but never gated
    (hardware-variable and not in the NFR-016 metric set).
    """
    failures: list[str] = []
    for name in _GATED:
        base_v = _metric(baseline, name)
        cand_v = _metric(candidate, name)
        if base_v <= 0:
            continue
        drop = (base_v - cand_v) / base_v
        if drop > REGRESSION_THRESHOLD + _REGRESSION_EPSILON:
            failures.append(
                f"{name}: baseline={base_v:.6f} candidate={cand_v:.6f} "
                f"drop={drop * 100:.2f}% (>{REGRESSION_THRESHOLD * 100:.0f}%)"
            )
    return GateResult(passed=not failures, failures=failures)


def resolve_git_sha() -> str:
    """Resolve the commit SHA: ``GITHUB_SHA`` env, then ``git``, else unknown.

    The ``git`` executable is resolved to an absolute path via
    ``shutil.which`` (no partial-path lookup), invoked with a fixed argv
    list, ``shell=False``, and zero untrusted input — there is no
    command-injection surface.
    """
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    git_exe = shutil.which("git")
    if git_exe is None:
        return "unknown"
    try:
        cp = subprocess.run(  # noqa: S603  # nosec B603 - absolute git path, fixed argv, shell=False
            [git_exe, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return cp.stdout.strip() or "unknown"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _run_validation_for_scorecard() -> ValidationResult:
    from pathlib import Path

    from seerflow.lanl.validator import run_validation

    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "lanl"
    return run_validation(fixtures)


def _run_benchmark_for_scorecard() -> BenchmarkResult:
    from seerflow.launch.benchmark import run_benchmark

    return run_benchmark(DEFAULT_BENCHMARK_EVENTS)


def run_scorecard(out_path: Path, baseline_path: Path | None) -> int:
    """Run harness + benchmark, write the artifact, optionally gate.

    Returns a process exit code: ``0`` on pass, ``1`` on regression or a
    missing baseline (fail-closed).
    """
    validation = _run_validation_for_scorecard()
    benchmark = _run_benchmark_for_scorecard()
    sc = build_scorecard(
        validation,
        benchmark,
        git_sha=resolve_git_sha(),
        timestamp=_now_iso(),
    )
    merged = append_history(scorecard_to_dict(sc), out_path)
    out_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if baseline_path is None:
        return 0
    if not baseline_path.exists():
        # CLI stdout is the gate contract (matches launch.benchmark.main).
        print(  # noqa: T201 -- CLI stdout is the contract
            f"scorecard gate: baseline not found: {baseline_path}"
        )
        return 1
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    result = evaluate_regression(merged, baseline)
    if result.passed:
        print("scorecard gate: PASS")  # noqa: T201 -- CLI stdout is the contract
        return 0
    print("scorecard gate: FAIL")  # noqa: T201 -- CLI stdout is the contract
    for f in result.failures:
        print(f"  - {f}")  # noqa: T201 -- CLI stdout is the contract
    return 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="seerflow.benchmark.scorecard",
        description=("Build the benchmark scorecard artifact and gate on NFR-016."),
    )
    parser.add_argument(
        "--out",
        default="benchmark-results.json",
        help="Path to write the (append-only) scorecard artifact.",
    )
    parser.add_argument(
        "--check",
        default=None,
        help="Baseline JSON to gate against; fail on >5%% regression.",
    )
    ns = parser.parse_args(argv)
    return run_scorecard(
        Path(ns.out),
        Path(ns.check) if ns.check else None,
    )


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))
