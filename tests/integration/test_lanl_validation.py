"""E2E validation: LANL correlation detects 3+ attack patterns.

This is the GATE test for S-045. If correlation doesn't produce
meaningfully better detection than single-source analysis, the
project needs fundamental reassessment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


@pytest.fixture()
def validation_result():
    """Run the full LANL validation pipeline once, cache for all tests."""
    from seerflow.lanl.validator import run_validation

    return run_validation(FIXTURES_DIR)


class TestLANLCorrelationValidation:
    """GATE: Correlation engine must detect 3+ attack patterns on LANL data."""

    def test_detects_three_or_more_attack_patterns(self, validation_result) -> None:
        """The core gate test: at least 3 distinct correlation rules fire on red-team activity."""
        assert len(validation_result.patterns_detected) >= 3, (
            f"Only {len(validation_result.patterns_detected)} patterns detected: "
            f"{validation_result.patterns_detected}. Need >= 3."
        )

    def test_has_true_positives(self, validation_result) -> None:
        """At least some alerts should correspond to real red-team activity."""
        assert validation_result.true_positives > 0, "No true positive detections"

    def test_precision_is_nonzero(self, validation_result) -> None:
        """Not all alerts should be false positives."""
        assert validation_result.precision > 0, "Zero precision — all alerts are false positives"

    def test_recall_is_nonzero(self, validation_result) -> None:
        """At least some red-team activity should be detected."""
        assert validation_result.recall > 0, "Zero recall — no red-team events detected"

    def test_false_positive_rate_is_reasonable(self, validation_result) -> None:
        """FP rate should be under 90%."""
        total = validation_result.true_positives + validation_result.false_positives
        if total > 0:
            fp_rate = validation_result.false_positives / total
            assert fp_rate < 0.9, f"False positive rate too high: {fp_rate:.1%}"

    def test_detection_latency_measured(self, validation_result) -> None:
        """Detection latency must be measured for at least one rule."""
        assert len(validation_result.detection_latency_s) > 0, "No detection latency data"

    def test_events_were_processed(self, validation_result) -> None:
        """Sanity check: events were actually processed."""
        assert validation_result.total_events_processed > 0

    def test_alerts_were_generated(self, validation_result) -> None:
        """Sanity check: the engine generated alerts."""
        assert validation_result.total_alerts > 0

    def test_f1_score_is_positive(self, validation_result) -> None:
        """F1 must be > 0 -- proves the harness produces a usable launch metric."""
        assert validation_result.f1_score > 0, "F1 score is zero"
        assert 0.0 <= validation_result.f1_score <= 1.0

    def test_false_positive_rate_is_bounded(self, validation_result) -> None:
        """FP-rate must be a valid probability and reasonably low."""
        assert 0.0 <= validation_result.false_positive_rate <= 1.0
        assert validation_result.false_positive_rate < 0.5, (
            f"FP-rate too high: {validation_result.false_positive_rate:.2%}"
        )


class TestValidationReport:
    """Tests that the validation produces data suitable for reporting."""

    def test_patterns_include_expected_rules(self, validation_result) -> None:
        """At least brute-force and credential-stuffing should fire."""
        expected = {"brute-force-lateral-movement", "credential-stuffing"}
        detected = validation_result.patterns_detected
        missing = expected - detected
        assert not missing, f"Expected patterns not detected: {missing}"

    def test_detection_latency_values_are_non_negative(self, validation_result) -> None:
        for rule, latency in validation_result.detection_latency_s.items():
            assert latency >= 0, f"Negative latency for {rule}: {latency}"
