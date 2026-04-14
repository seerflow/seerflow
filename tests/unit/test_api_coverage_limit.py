"""Unit tests for the coverage_limit() closure (S-186)."""

from __future__ import annotations

from seerflow.api import limits
from seerflow.config import SeerflowConfig


def test_coverage_limit_default_matches_config() -> None:
    assert limits.coverage_limit() == SeerflowConfig().api_coverage_rate_limit


def test_configure_limiter_rebinds_coverage_limit() -> None:
    cfg = SeerflowConfig(api_coverage_rate_limit="3/minute")
    limits.configure_limiter(cfg)
    try:
        assert limits.coverage_limit() == "3/minute"
    finally:
        limits.configure_limiter(SeerflowConfig())
