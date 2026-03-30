"""Tests for Watermark-based late arrival tolerance."""
from __future__ import annotations

from seerflow.correlation.watermark import Watermark


class TestWatermark:
    def test_initial_watermark_is_zero(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        assert wm.current_ns == 0

    def test_advance_updates_watermark(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        wm.advance(1_000_000_000)
        assert wm.current_ns == 1_000_000_000

    def test_advance_is_monotonic(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        wm.advance(2_000_000_000)
        wm.advance(1_000_000_000)  # older event
        assert wm.current_ns == 2_000_000_000  # still at max

    def test_is_late_returns_false_for_current_event(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        wm.advance(100_000_000_000)
        assert wm.is_late(100_000_000_000) is False

    def test_is_late_returns_false_within_tolerance(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)  # 30s tolerance
        wm.advance(100_000_000_000)
        # Event 20s behind watermark — within 30s tolerance
        assert wm.is_late(80_000_000_000) is False

    def test_is_late_returns_true_beyond_tolerance(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)  # 30s tolerance
        wm.advance(100_000_000_000)
        # Event 50s behind watermark — beyond 30s tolerance
        assert wm.is_late(50_000_000_000) is True

    def test_is_late_boundary_exactly_at_tolerance(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        wm.advance(100_000_000_000)
        # Event exactly at tolerance boundary — NOT late
        assert wm.is_late(70_000_000_000) is False

    def test_is_late_before_any_advance(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        # No advance yet — nothing is late
        assert wm.is_late(1_000_000_000) is False

    def test_advance_with_future_event(self) -> None:
        wm = Watermark(tolerance_ns=30_000_000_000)
        wm.advance(200_000_000_000)
        assert wm.current_ns == 200_000_000_000
