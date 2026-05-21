"""Unit tests for the host-load-aware IoC-matcher rebuild timing decision.

S-237 (SEE-261): the integration test
``test_matcher_rebuilds_within_one_second_for_100k_indicators`` asserts a
hard wall-clock budget for a genuinely CPU-bound 100K-indicator rebuild.
Under full-suite parallel load on a saturated host the rebuild legitimately
exceeds the 1.0 s non-coverage ceiling. ``_rebuild_timing_decision`` makes
the *timing ceiling* host-load-aware (mirroring the existing coverage-aware
branch) while the functional assertions stay unconditional. These tests pin
its branch behaviour deterministically, independent of the host's real load.
"""

from __future__ import annotations

import pytest

from tests.integration.test_ioc_matcher_pipeline import _rebuild_timing_decision


class TestRebuildTimingDecision:
    """Branch matrix for the host-load-aware budget helper."""

    def test_unloaded_host_uses_strict_one_second_budget(self) -> None:
        should_assert, budget_s, reason = _rebuild_timing_decision(
            load1=0.1, cpu_count=8, under_coverage=False
        )
        assert should_assert is True
        assert budget_s == 1.0
        assert "strict" in reason.lower()

    def test_unloaded_host_under_coverage_uses_three_second_budget(self) -> None:
        should_assert, budget_s, _reason = _rebuild_timing_decision(
            load1=0.1, cpu_count=8, under_coverage=True
        )
        assert should_assert is True
        assert budget_s == 3.0

    def test_saturated_host_skips_the_timing_ceiling(self) -> None:
        should_assert, _budget_s, reason = _rebuild_timing_decision(
            load1=20.0, cpu_count=8, under_coverage=False
        )
        assert should_assert is False
        assert "satur" in reason.lower()

    def test_saturated_host_still_skips_under_coverage(self) -> None:
        should_assert, _budget_s, reason = _rebuild_timing_decision(
            load1=40.0, cpu_count=8, under_coverage=True
        )
        assert should_assert is False
        assert "satur" in reason.lower()

    def test_load_unknown_falls_back_to_strict_budget(self) -> None:
        should_assert, budget_s, reason = _rebuild_timing_decision(
            load1=None, cpu_count=8, under_coverage=False
        )
        assert should_assert is True
        assert budget_s == 1.0
        assert "unknown" in reason.lower()

    @pytest.mark.parametrize("bad_cpu", [0, -1])
    def test_nonpositive_cpu_count_treated_as_single_cpu(self, bad_cpu: int) -> None:
        # load1=1.4 with cpu treated as 1 → load_per_cpu 1.4 < 1.5 → strict.
        should_assert, budget_s, _reason = _rebuild_timing_decision(
            load1=1.4, cpu_count=bad_cpu, under_coverage=False
        )
        assert should_assert is True
        assert budget_s == 1.0

        # load1=1.5 with cpu treated as 1 → load_per_cpu 1.5 >= 1.5 → skip.
        # No ZeroDivisionError must be raised for cpu_count <= 0.
        skip_assert, _b, skip_reason = _rebuild_timing_decision(
            load1=1.5, cpu_count=bad_cpu, under_coverage=False
        )
        assert skip_assert is False
        assert "satur" in skip_reason.lower()

    def test_threshold_boundary_is_inclusive_at_one_point_five(self) -> None:
        # Exactly at the 1.5 load-per-cpu boundary → saturated (skip).
        at_boundary, _b, _r = _rebuild_timing_decision(
            load1=12.0, cpu_count=8, under_coverage=False
        )
        assert at_boundary is False
        # Just below the boundary → strict.
        below, _b2, _r2 = _rebuild_timing_decision(load1=11.9, cpu_count=8, under_coverage=False)
        assert below is True
