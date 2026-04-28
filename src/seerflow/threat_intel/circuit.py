"""Per-feed auth-failure circuit breaker.

States: closed -> open (after N consecutive auth failures) -> half-open
(after open-window elapses, one probe granted) -> closed (probe succeeds)
or open (probe fails). Time source is injectable so tests are deterministic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class AuthCircuitBreaker:
    threshold: int = 3
    open_seconds: float = 3600.0
    now_fn: Callable[[], float] = time.monotonic

    # ``init=False`` keeps these fields out of the generated ``__init__``
    # so callers cannot bypass the state-machine invariants by passing
    # ``_failures=10`` etc. at construction time.
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _half_open: bool = field(default=False, init=False)

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self.now_fn() - self._opened_at >= self.open_seconds:
            self._half_open = True
            return True
        return False

    def is_open(self) -> bool:
        return self._opened_at is not None and not self._half_open

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open = False

    def record_failure(self) -> None:
        if self._half_open:
            self._opened_at = self.now_fn()
            self._half_open = False
            return
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = self.now_fn()
