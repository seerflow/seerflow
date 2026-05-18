"""E2E validation: the full detection stack runs on the synthetic LANL
subset (S-305 / FR-073).

This is no longer a correlation-only gate. The harness routes RawEvents
through the complete ``assemble_handler`` wiring (Drain3 → ML → Sigma →
UEBA → IoC → correlation) — the identical path as live ``seerflow start``.
The test asserts the run is honestly scoped and the ValidationResult is
internally consistent on the synthetic subset; it deliberately does NOT
assert specific correlation rule names or a minimum pattern count, which
encoded the old correlation-only behaviour the functional review flagged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture(scope="module")
def validation_result():
    """Run the full-stack LANL validation once, cache for all tests."""
    from seerflow.lanl.validator import run_validation

    return run_validation(FIXTURES_DIR)


class TestLANLFullStackValidation:
    """The harness exercises the real product on the synthetic subset."""

    def test_events_were_processed(self, validation_result) -> None:
        assert validation_result.total_events_processed > 0

    def test_scope_label_is_honest(self, validation_result) -> None:
        """AC5: scope label names the synthetic subset, not full LANL."""
        label = validation_result.scope_label.lower()
        assert "synthetic lanl subset" in label
        assert "end-to-end on full lanl" not in label
        assert "full detection stack" in label

    def test_per_family_is_a_recognised_subset(self, validation_result) -> None:
        assert isinstance(validation_result.per_family, dict)
        assert set(validation_result.per_family).issubset(
            {"ml", "sigma", "correlation", "ueba", "ioc"}
        )

    def test_metrics_are_valid_probabilities(self, validation_result) -> None:
        assert 0.0 <= validation_result.precision <= 1.0
        assert 0.0 <= validation_result.recall <= 1.0
        assert 0.0 <= validation_result.f1_score <= 1.0
        assert 0.0 <= validation_result.false_positive_rate <= 1.0

    def test_counts_are_internally_consistent(self, validation_result) -> None:
        r = validation_result
        assert r.total_alerts == r.true_positives + r.false_positives
        assert r.true_positives >= 0
        assert r.false_positives >= 0
        assert r.false_negatives >= 0

    def test_per_family_submetrics_consistent(self, validation_result) -> None:
        for _fam, m in validation_result.per_family.items():
            assert m.total_alerts == m.true_positives + m.false_positives
            assert 0.0 <= m.precision <= 1.0
            assert 0.0 <= m.f1_score <= 1.0
            assert m.false_negatives == 0  # not attributable per-family
