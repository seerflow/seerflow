"""S-090 Show HN launch kit: deterministic demo, benchmark harness,
results renderer, asciinema command builder, and blog draft.

Reuses the public pipeline API (no duplicate pipeline wiring) and links to
S-088's LANL detection-quality numbers (never recomputed here).
"""

from __future__ import annotations

from seerflow.launch.benchmark import BenchmarkResult, run_benchmark
from seerflow.launch.demo import run_demo
from seerflow.launch.record import build_asciinema_command
from seerflow.launch.report import render_benchmark_report
from seerflow.launch.synthetic import build_events

__all__ = [
    "BenchmarkResult",
    "build_asciinema_command",
    "build_events",
    "render_benchmark_report",
    "run_benchmark",
    "run_demo",
]
