"""Unit tests for the coverage_limit() closure (S-186)."""

from __future__ import annotations

from seerflow.api import limits
from seerflow.config import SeerflowConfig


def test_coverage_limit_default_matches_config() -> None:
    # Reset module-level state — other tests in the suite may have rebound
    # _current_coverage_limit via configure_limiter(non-default).
    limits.configure_limiter(SeerflowConfig())
    assert limits.coverage_limit() == SeerflowConfig().api_coverage_rate_limit


def test_configure_limiter_rebinds_coverage_limit() -> None:
    cfg = SeerflowConfig(api_coverage_rate_limit="3/minute")
    limits.configure_limiter(cfg)
    try:
        assert limits.coverage_limit() == "3/minute"
    finally:
        limits.configure_limiter(SeerflowConfig())
