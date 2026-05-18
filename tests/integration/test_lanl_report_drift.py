"""Drift guards: published numbers must be harness-derived, never hand-typed.

``docs/`` is git-excluded so there is no committed Markdown report file to
diff. Instead these tests assert (a) the renderer output is consistent
with the live ValidationResult and (b) the README Validation table equals
the freshly computed metrics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"
README = Path(__file__).resolve().parents[2] / "README.md"


@pytest.fixture(scope="module")
def result():
    from seerflow.lanl.validator import run_validation

    return run_validation(FIXTURES_DIR)


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def test_readme_has_validation_section():
    text = README.read_text(encoding="utf-8")
    assert "## Validation" in text


def test_readme_validation_table_matches_harness(result):
    text = README.read_text(encoding="utf-8")
    # Each metric row must contain the harness-computed value.
    assert f"| Precision | {_pct(result.precision)} |" in text
    assert f"| Recall | {_pct(result.recall)} |" in text
    assert f"| F1 score | {_pct(result.f1_score)} |" in text
    assert f"| False-positive rate | {_pct(result.false_positive_rate)} |" in text
    assert f"| Events processed | {result.total_events_processed} |" in text


def test_readme_validation_labels_synthetic_subset():
    text = README.read_text(encoding="utf-8")
    section = text.split("## Validation", 1)[1].split("\n## ", 1)[0]
    assert "synthetic" in section.lower()
    assert "tests/integration/test_lanl_validation.py" in section


def test_renderer_output_matches_harness(result):
    from seerflow.lanl.report import render_validation_report

    md = render_validation_report(result, dataset_label="synthetic LANL subset", date="2026-05-16")
    assert f"| Precision | {_pct(result.precision)} |" in md
    assert f"| F1 score | {_pct(result.f1_score)} |" in md
    assert f"| False-positive rate | {_pct(result.false_positive_rate)} |" in md
    assert f"| Total events processed | {result.total_events_processed} |" in md
    assert str(len(result.patterns_detected)) in md
    # S-305: the honest scope label must be echoed verbatim.
    assert result.scope_label in md
    assert "## Detection by Family" in md


def test_renderer_main_writes_file(result, tmp_path):
    from seerflow.lanl.report import _main

    out = tmp_path / "report.md"
    rc = _main(["report", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("# LANL")


def test_renderer_main_prints_to_stdout(capsys):
    from seerflow.lanl.report import _main

    rc = _main(["report"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.startswith("# LANL")
