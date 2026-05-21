"""Test fixtures shared across the Seerflow test suite.

S-181: the slowapi ``Limiter`` is a process-global singleton (routes
bind decorators at import time). Each test must observe a predictable
initial state, so the autouse fixture below rewinds the limiter to
``enabled=False`` with a fresh in-memory storage before every test.

S-232 (SEE-242): time-windowed API routes read the wall clock at
request time. A test that snapshots ``now`` then performs a slow write
phase (e.g. flooding 10_050 alerts) lets the route's ``now`` advance
past the snapshot, sliding query windows and flaking under CI coverage
load. ``FrozenDatetime`` and ``pin_time_ns`` are the shared, opt-in
clock-pinning tools; they replace three previously ad-hoc shims.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from slowapi import Limiter

from seerflow.api import limits as _limits
from seerflow.api.limits import _key_func
from seerflow.config import SeerflowConfig

if TYPE_CHECKING:
    from collections.abc import Iterator


class FrozenDatetime:
    """Stand-in for ``datetime`` with a frozen ``now`` and passthrough.

    Patch onto a route module's ``datetime`` binding (e.g.
    ``monkeypatch.setattr("seerflow.api.routes.sigma.datetime",
    FrozenDatetime(now_ns))``) so the route's
    ``datetime.now(UTC).timestamp()`` returns a deterministic value
    while every other ``datetime`` attribute the route might use is
    delegated to the real class.

    Promoted verbatim from the S-154 ``_FrozenDatetime`` shim in
    ``tests/integration/api/test_sigma_timeline.py`` so the same shape
    is reused instead of re-declared per file (SEE-242).
    """

    def __init__(self, frozen_ns: int) -> None:
        self._frozen = datetime.fromtimestamp(frozen_ns / 1_000_000_000, tz=UTC)

    def now(self, tz: object = None) -> datetime:
        # now(tz) ignores tz; routes always pass UTC
        return self._frozen

    def __getattr__(self, name: str) -> object:
        return getattr(datetime, name)


def pin_time_ns(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    ns: int,
) -> None:
    """Pin a route module's ``time.time_ns`` binding to a fixed value.

    For routes that read ``time.time_ns()`` directly (e.g.
    ``seerflow.api.routes.entities``), this freezes the route's request
    clock so a slow test write phase cannot slide a query window past
    seeded data.

    ``ns`` is captured by value into the closure, so reassigning the
    caller's snapshot variable after this call cannot retroactively
    change what the route observes.

    ``target`` is supplied by the caller (e.g.
    ``"seerflow.api.routes.entities.time.time_ns"``). The string is
    intentionally explicit at the call site: that path relies on the
    route module using ``import time`` then ``time.time_ns()``. A future
    refactor to ``from time import time_ns`` must update the target to
    ``seerflow.api.routes.entities.time_ns`` — keeping the string at the
    call site makes that coupling visible rather than hiding it here.
    """
    monkeypatch.setattr(target, lambda: ns)


@pytest.fixture(autouse=True)
def _reset_api_limiter() -> Iterator[None]:
    """Reset the module-level ``limiter`` singleton to a clean state.

    Without this, a test that enables rate limiting leaks its
    in-memory counters into the next test. Execution is global so the
    fix must also be global. S-185 routes the internal-attribute rebind
    through the same helper production uses, so a slowapi internal
    rename fails in tests too.
    """
    from seerflow.api.limits import _rebind_limiter_internals

    def _reset() -> None:
        fresh = Limiter(key_func=_key_func, storage_uri="memory://", enabled=False)
        _rebind_limiter_internals(_limits.limiter, fresh)
        _limits.limiter.enabled = False
        defaults = SeerflowConfig()
        _limits._current_list_limit = defaults.api_list_rate_limit
        _limits._current_detail_limit = defaults.api_detail_rate_limit
        _limits._current_coverage_limit = defaults.api_coverage_rate_limit

    _reset()
    yield
    # Symmetric teardown: leave the singleton clean for any consumer outside
    # the pytest lifecycle (REPL reuse, --co resume) that may run after.
    _reset()
