"""Test fixtures shared across the Seerflow test suite.

S-181: the slowapi ``Limiter`` is a process-global singleton (routes
bind decorators at import time). Each test must observe a predictable
initial state, so the autouse fixture below rewinds the limiter to
``enabled=False`` with a fresh in-memory storage before every test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from slowapi import Limiter

from seerflow.api import limits as _limits
from seerflow.api.limits import _key_func
from seerflow.config import SeerflowConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _reset_api_limiter() -> Iterator[None]:
    """Reset the module-level ``limiter`` singleton to a clean state.

    Without this, a test that enables rate limiting leaks its
    in-memory counters into the next test. Execution is global so the
    fix must also be global.
    """
    fresh = Limiter(key_func=_key_func, storage_uri="memory://", enabled=False)
    _limits.limiter.enabled = False
    _limits.limiter._storage = fresh._storage
    _limits.limiter._limiter = fresh._limiter
    defaults = SeerflowConfig()
    _limits._current_list_limit = defaults.api_list_rate_limit
    _limits._current_detail_limit = defaults.api_detail_rate_limit
    yield
