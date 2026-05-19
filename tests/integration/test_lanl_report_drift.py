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


_ENGINE_TOKENS = ("drain3", "ml", "sigma", "ueba", "ioc", "correlation")
_OVERCLAIM_VARIANTS = (
    "end-to-end on the full lanl dataset",
    "end to end on the full lanl dataset",
)


def _validation_section(text: str) -> str:
    """Return the README ``## Validation`` section body (until next ``## ``)."""
    return text.split("## Validation", 1)[1].split("\n## ", 1)[0]


def _assert_scoped(label: str, blob: str) -> None:
    """Enforce NFR-017 on a doc blob: positive scope tokens present, no
    *unqualified* 'end-to-end on the full LANL dataset' overclaim.

    The overclaim phrase is allowed only when a negation cue ("not")
    appears in the ~60 chars immediately preceding it, so honestly-scoped
    prose ('it does **not** by itself constitute "end-to-end on the full
    LANL dataset"') passes while a bare affirmative claim fails. Matched
    on engine *names*, never the arrow glyph (README uses ASCII '->',
    the docstring uses Unicode '->')."""
    low = blob.lower()
    assert "synthetic" in low, f"{label}: missing 'synthetic' scope word"
    for tok in _ENGINE_TOKENS:
        assert tok in low, f"{label}: missing exercised-engine token {tok!r}"
    for variant in _OVERCLAIM_VARIANTS:
        idx = low.find(variant)
        if idx != -1:
            window = low[max(0, idx - 60) : idx]
            assert "not" in window, (
                f"{label}: unqualified overclaim {variant!r} present without "
                f"a preceding negation cue ('not') (NFR-017)"
            )


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
    section = _validation_section(text)
    # Retained: dataset name + reproduce command must be present.
    assert "synthetic" in section.lower()
    assert "tests/integration/test_lanl_validation.py" in section
    # NFR-017: explicit scope label (dataset path + engines) and no overclaim.
    assert "tests/fixtures/lanl" in section.lower()
    _assert_scoped("README Validation section", section)


def test_readme_reflects_harness_scope_label(result):
    """AC3-iv: the salient tokens of the harness scope_label appear in the
    README Validation section (not the verbatim string -- that would be
    brittle)."""
    section = _validation_section(README.read_text(encoding="utf-8")).lower()
    label = result.scope_label.lower()
    assert "synthetic" in label and "synthetic" in section
    assert "tests/fixtures/lanl" in label
    assert "tests/fixtures/lanl" in section


def test_validator_module_docstring_is_scoped():
    """AC1/AC4: the validator module docstring must scope the run to the
    synthetic subset and must not reassert an unqualified full-dataset
    'end-to-end' claim."""
    import seerflow.lanl.validator as v

    doc = v.__doc__ or ""
    assert "synthetic lanl subset" in doc.lower()
    _assert_scoped("validator.py module docstring", doc)


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
