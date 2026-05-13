"""Unit tests for the coverage_limit() closure (S-186)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.api import limits
from seerflow.config import SeerflowConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_limiter_state() -> Iterator[None]:
    # Module-level _current_coverage_limit is mutated by configure_limiter,
    # so reset around every test to keep cases independent of ordering.
    limits.configure_limiter(SeerflowConfig())
    yield
    limits.configure_limiter(SeerflowConfig())


def test_coverage_limit_default_matches_config() -> None:
    assert limits.coverage_limit() == SeerflowConfig().api_coverage_rate_limit


def test_configure_limiter_rebinds_coverage_limit() -> None:
    cfg = SeerflowConfig(api_coverage_rate_limit="3/minute")
    limits.configure_limiter(cfg)
    assert limits.coverage_limit() == "3/minute"
