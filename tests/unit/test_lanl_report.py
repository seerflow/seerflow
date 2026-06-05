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


def test_render_validation_report_exported_from_package():
    import seerflow.lanl as lanl_pkg

    assert hasattr(lanl_pkg, "render_validation_report")
    assert "render_validation_report" in lanl_pkg.__all__


# ---------------------------------------------------------------------------
# S-311 / FR-079 — AUC line + per-attack-scenario MTTD table
# ---------------------------------------------------------------------------


def test_report_contains_auc_line(render):
    from seerflow.lanl.attack_metrics import AttackScenarioMetrics

    r = ValidationResult(
        true_positives=2,
        false_positives=10,
        false_negatives=4,
        precision=0.1667,
        recall=0.3333,
        f1_score=0.2222,
        false_positive_rate=0.8333,
        detection_latency_s={},
        patterns_detected=frozenset({"c2-beaconing"}),
        total_events_processed=137,
        total_alerts=12,
        auc=0.0,
        attack_scenarios=(
            AttackScenarioMetrics(
                name="c2-beaconing",
                first_event_time_s=300,
                record_count=2,
                detected=True,
                mttd_seconds=300.0,
                missed_record_count=0,
            ),
            AttackScenarioMetrics(
                name="brute-force-lateral-movement",
                first_event_time_s=110,
                record_count=1,
                detected=False,
                mttd_seconds=None,
                missed_record_count=1,
            ),
        ),
    )
    out = render(r, dataset_label="synthetic LANL subset", date="2026-05-16")
    assert "## Attack-Level Metrics" in out
    assert "AUC" in out
    assert "0.0000" in out  # AUC formatted to 4dp
    # Per-scenario MTTD table: detected scenario shows seconds, undetected "not detected".
    assert "c2-beaconing" in out
    assert "300.0" in out
    assert "not detected" in out


def test_report_auc_none_renders_na(render):
    out = render(_make_result(), dataset_label="synthetic LANL subset", date="2026-05-16")
    # _make_result leaves auc=None -> rendered as N/A, never a bare "None".
    assert "N/A" in out


# ---------------------------------------------------------------------------
# S-359 — _main write-path hardening (refuse symlink-follow writes)
# ---------------------------------------------------------------------------


def test_main_writes_to_regular_path(tmp_path):
    """_main writes the report to a normal (non-symlink) argv[1] path."""
    from seerflow.lanl import report_renderer

    out = tmp_path / "report.md"
    rc = report_renderer._main(["prog", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("# LANL")


def test_main_refuses_symlink_target(tmp_path):
    """_main refuses to follow a symlink at argv[1] (no symlink-follow write)."""
    from seerflow.lanl import report_renderer

    real = tmp_path / "real.md"
    real.write_text("SENTINEL", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="symlink"):
        report_renderer._main(["prog", str(link)])

    # The real file must be untouched (no follow-through write).
    assert real.read_text(encoding="utf-8") == "SENTINEL"
