"""Per-feed TAXII metrics snapshots, exposed via /api/v1/stats.

Mirror the immutable-snapshot pattern in ``seerflow.api.metrics``: the
registry holds mutable counters; each call to ``snapshot()`` /
``aggregate()`` returns a frozen dataclass that the API layer can
serialize without further locking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from seerflow.models.indicator import IndicatorType


@dataclass(frozen=True, slots=True)
class TAXIIFeedMetrics:
    polls_ok_total: int
    polls_failed_total: int
    polls_auth_failed_total: int
    indicators_seen_total: dict[IndicatorType, int]
    indicators_truncated_total: int
    last_successful_poll_at_ns: int | None
    circuit_open: bool


@dataclass(frozen=True, slots=True)
class TAXIIMetricsAggregate:
    feeds: dict[str, TAXIIFeedMetrics] = field(default_factory=dict)


class TAXIIMetricsRegistry:
    """Mutable, thread-safe registry of per-feed counters."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._feeds: dict[str, _MutableFeedState] = {}

    def _state(self, feed_id: str) -> _MutableFeedState:
        st = self._feeds.get(feed_id)
        if st is None:
            st = _MutableFeedState()
            self._feeds[feed_id] = st
        return st

    def record_poll_ok(
        self,
        feed_id: str,
        *,
        at_ns: int,
        indicators_by_type: dict[str, int],
    ) -> None:
        with self._lock:
            st = self._state(feed_id)
            st.polls_ok_total += 1
            st.last_successful_poll_at_ns = at_ns
            for k, v in indicators_by_type.items():
                st.indicators_seen_total[k] = st.indicators_seen_total.get(k, 0) + v

    def record_poll_failed(self, feed_id: str, *, auth: bool) -> None:
        with self._lock:
            st = self._state(feed_id)
            if auth:
                st.polls_auth_failed_total += 1
            else:
                st.polls_failed_total += 1

    def record_truncated(self, feed_id: str, *, count: int) -> None:
        with self._lock:
            st = self._state(feed_id)
            st.indicators_truncated_total += count

    def set_circuit_open(self, feed_id: str, *, open_: bool) -> None:
        with self._lock:
            self._state(feed_id).circuit_open = open_

    def snapshot(self, feed_id: str) -> TAXIIFeedMetrics:
        with self._lock:
            st = self._feeds.get(feed_id) or _MutableFeedState()
            return TAXIIFeedMetrics(
                polls_ok_total=st.polls_ok_total,
                polls_failed_total=st.polls_failed_total,
                polls_auth_failed_total=st.polls_auth_failed_total,
                indicators_seen_total=cast(
                    "dict[IndicatorType, int]", dict(st.indicators_seen_total)
                ),
                indicators_truncated_total=st.indicators_truncated_total,
                last_successful_poll_at_ns=st.last_successful_poll_at_ns,
                circuit_open=st.circuit_open,
            )

    def aggregate(self) -> TAXIIMetricsAggregate:
        with self._lock:
            feed_ids = list(self._feeds)
        # Snapshot under per-call lock acquisition; ``snapshot`` re-acquires
        # the lock for each feed which keeps contention minimal.
        return TAXIIMetricsAggregate(
            feeds={fid: self.snapshot(fid) for fid in feed_ids},
        )


@dataclass
class _MutableFeedState:
    polls_ok_total: int = 0
    polls_failed_total: int = 0
    polls_auth_failed_total: int = 0
    indicators_seen_total: dict[str, int] = field(default_factory=dict)
    indicators_truncated_total: int = 0
    last_successful_poll_at_ns: int | None = None
    circuit_open: bool = False
