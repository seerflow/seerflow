"""Unit tests for the LANL validation Markdown report renderer.

Tests follow TDD (RED -> GREEN -> REFACTOR). The renderer is a pure
function -- given a ValidationResult it must deterministically produce
Markdown containing the exact metrics. No I/O, no datetime.now().
"""

from __future__ import annotations

import pytest

from seerflow.lanl.validator import ValidationResult


def _make_result(
    *,
    true_positives: int = 12,
    false_positives: int = 1,
    false_negatives: int = 0,
    precision: float = 0.9231,
    recall: float = 1.0,
    f1_score: float = 0.96,
    false_positive_rate: float = 0.0769,
    detection_latency_s: dict[str, float] | None = None,
    patterns_detected: frozenset[str] | None = None,
    total_events_processed: int = 203,
    total_alerts: int = 13,
) -> ValidationResult:
    return ValidationResult(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1_score=f1_score,
        false_positive_rate=false_positive_rate,
        detection_latency_s=detection_latency_s
        or {"brute-force-lateral-movement": 0.0, "credential-stuffing": 97.4},
        patterns_detected=patterns_detected
        or frozenset({"brute-force-lateral-movement", "credential-stuffing", "c2-beaconing"}),
        total_events_processed=total_events_processed,
        total_alerts=total_alerts,
    )


@pytest.fixture
def render():
    from seerflow.lanl.report import render_validation_report

    return render_validation_report


def test_report_is_markdown_string(render):
    out = render(_make_result(), dataset_label="synthetic LANL subset", date="2026-05-16")
    assert isinstance(out, str)
    assert out.startswith("# LANL")


def test_report_is_deterministic_for_fixed_inputs(render):
    r = _make_result()
    a = render(r, dataset_label="synthetic LANL subset", date="2026-05-16")
    b = render(r, dataset_label="synthetic LANL subset", date="2026-05-16")
    assert a == b


def test_report_contains_injected_date_and_label(render):
    out = render(_make_result(), dataset_label="synthetic LANL subset", date="2026-05-16")
    assert "2026-05-16" in out
    assert "synthetic LANL subset" in out


def test_report_contains_f1_and_fp_rate(render):
    out = render(
        _make_result(f1_score=0.9600, false_positive_rate=0.0769),
        dataset_label="synthetic LANL subset",
        date="2026-05-16",
    )
    assert "F1" in out
    assert "96.00%" in out  # f1 rendered as percentage to 2dp
    assert "7.69%" in out  # fp-rate rendered as percentage to 2dp


def test_report_contains_precision_recall_counts(render):
    out = render(
        _make_result(precision=0.9231, recall=1.0, true_positives=12, false_positives=1),
        dataset_label="synthetic LANL subset",
        date="2026-05-16",
    )
    assert "92.31%" in out
    assert "100.00%" in out
    assert "| True positives | 12 |" in out
    assert "| False positives | 1 |" in out


def test_report_lists_detected_patterns_sorted(render):
    out = render(
        _make_result(
            patterns_detected=frozenset({"c2-beaconing", "brute-force-lateral-movement"})
        ),
        dataset_label="synthetic LANL subset",
        date="2026-05-16",
    )
    # Sorted for determinism
    idx_bf = out.index("brute-force-lateral-movement")
    idx_c2 = out.index("c2-beaconing")
    assert idx_bf < idx_c2


def test_report_contains_reproducibility_section(render):
    out = render(_make_result(), dataset_label="synthetic LANL subset", date="2026-05-16")
    assert "Run on the full LANL dataset" in out
    assert "python -m seerflow.lanl.report" in out
    assert "auth.csv" in out


def test_report_contains_detection_latency_table(render):
    out = render(
        _make_result(detection_latency_s={"brute-force-lateral-movement": 0.0}),
        dataset_label="synthetic LANL subset",
        date="2026-05-16",
    )
    assert "Detection Latency" in out
    assert "brute-force-lateral-movement" in out
