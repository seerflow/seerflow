"""Drift guard: README + SHOWHN must stay wired to the launch harness (S-090).

Perf numbers are hardware-dependent, so this asserts STRUCTURE + WIRING
(commands present, columns present, report shape), never a pinned magnitude.
"""

from __future__ import annotations

from pathlib import Path

from seerflow.launch.benchmark import run_benchmark
from seerflow.launch.report import render_benchmark_report

_ROOT = Path(__file__).resolve().parents[2]
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_SHOWHN = (_ROOT / "src" / "seerflow" / "launch" / "SHOWHN.md").read_text(
    encoding="utf-8"
)


def test_report_contains_throughput_and_command(tmp_path) -> None:
    result = run_benchmark(60, seed=7, data_dir=tmp_path)
    out = render_benchmark_report(result, date="2026-05-16")
    assert f"{result.throughput_eps:,.0f} events/sec" in out
    assert "python -m seerflow.launch.benchmark" in out


def test_readme_benchmarks_references_harness() -> None:
    assert "python -m seerflow.launch.benchmark" in _README


def test_readme_comparison_has_wazuh_and_opensearch() -> None:
    compare = _README.split("## How Seerflow Compares", 1)[1]
    # The comparison table header is the first Markdown table row
    # ("| Dimension | ... |") after the section heading.
    header = next(
        line
        for line in compare.splitlines()
        if line.startswith("| Dimension")
    )
    assert "Wazuh" in header
    assert "OpenSearch" in header


def test_showhn_has_reproduce_commands() -> None:
    assert "python -m seerflow.launch.demo" in _SHOWHN
    assert "python -m seerflow.launch.benchmark" in _SHOWHN
    assert "python -m seerflow.lanl.report" in _SHOWHN
    assert "Validation" in _SHOWHN
