"""Tests for per-rule dedup window override wiring in the handler."""

from __future__ import annotations

from seerflow.config import AlertingConfig
from seerflow.pipeline.handler import _dedup_window_ns


class TestDedupWindowNs:
    """Unit tests for the _dedup_window_ns helper."""

    def test_returns_global_default_when_no_overrides(self) -> None:
        config = AlertingConfig(dedup_window_seconds=900)
        result = _dedup_window_ns("hst-anomaly", config)
        assert result == 900 * 1_000_000_000

    def test_returns_override_for_matching_rule(self) -> None:
        config = AlertingConfig(
            dedup_window_seconds=900,
            dedup_window_overrides=(("hst-anomaly", 300),),
        )
        result = _dedup_window_ns("hst-anomaly", config)
        assert result == 300 * 1_000_000_000

    def test_returns_global_default_for_non_matching_rule(self) -> None:
        config = AlertingConfig(
            dedup_window_seconds=900,
            dedup_window_overrides=(("sigma-brute-force", 3600),),
        )
        result = _dedup_window_ns("hst-anomaly", config)
        assert result == 900 * 1_000_000_000

    def test_first_match_wins(self) -> None:
        config = AlertingConfig(
            dedup_window_seconds=900,
            dedup_window_overrides=(
                ("hst-anomaly", 300),
                ("hst-anomaly", 600),
            ),
        )
        result = _dedup_window_ns("hst-anomaly", config)
        assert result == 300 * 1_000_000_000

    def test_multiple_rules_correct_match(self) -> None:
        config = AlertingConfig(
            dedup_window_seconds=900,
            dedup_window_overrides=(
                ("hst-anomaly", 300),
                ("sigma-brute-force", 3600),
                ("risk-accumulation", 1800),
            ),
        )
        assert _dedup_window_ns("sigma-brute-force", config) == 3600 * 1_000_000_000
        assert _dedup_window_ns("risk-accumulation", config) == 1800 * 1_000_000_000
        assert _dedup_window_ns("unknown-rule", config) == 900 * 1_000_000_000
