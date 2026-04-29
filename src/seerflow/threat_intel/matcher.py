"""Bloom-filter IoC matcher (S-068).

Builds + refreshes a bit-array Bloom filter (with a per-type confirmation
dict) from the IndicatorSnapshot blobs persisted by S-067's TAXII consumers.
Probes are O(1); confirmation eliminates Bloom false positives before any
match is dispatched.

S-069 subscribes to ``on_match`` and turns matches into Alerts; this module
does NOT call AlertStore.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import msgspec

from seerflow.models.indicator import IndicatorSnapshot
from seerflow.threat_intel._bloom import BloomParams, _BloomFilter

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.config import ThreatIntelConfig
    from seerflow.models.indicator import Indicator
    from seerflow.models.ioc_match import IoCMatch
    from seerflow.storage.protocols import ModelStore

_log = logging.getLogger("seerflow")


@dataclass(frozen=True, slots=True)
class IoCMatcherMetrics:
    """Immutable snapshot of matcher counters, surfaced via /api/v1/stats."""

    indicators_loaded: dict[str, int] = field(default_factory=dict)
    bit_array_bytes: int = 0
    expected_fpr: float = 0.0
    last_rebuild_at_ns: int | None = None
    rebuild_count: int = 0
    rebuild_failures_total: int = 0
    checks_total: int = 0
    bloom_hits_total: int = 0
    confirmed_matches_total: int = 0
    false_positives_total: int = 0


@dataclass(frozen=True, slots=True)
class _MatcherState:
    """Bloom + confirmation dict — atomically swapped on rebuild."""

    bloom: _BloomFilter
    by_type: dict[str, dict[str, Indicator]]
    indicators_loaded: dict[str, int]
    bit_array_bytes: int


class IoCMatcher:
    """Probes events against the threat-intel indicator set."""

    def __init__(
        self,
        *,
        config: ThreatIntelConfig,
        model_store: ModelStore,
        on_match: Callable[[IoCMatch], None] | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._cfg = config
        self._matcher_cfg = config.matcher
        self._store = model_store
        self._on_match = on_match
        self._clock_ns = clock_ns

        self._state: _MatcherState | None = None
        self._lock = threading.Lock()  # guards counters + rebuild exclusion
        self._rebuild_count = 0
        self._rebuild_failures_total = 0
        self._last_rebuild_at_ns: int | None = None
        self._checks_total = 0
        self._bloom_hits_total = 0
        self._confirmed_matches_total = 0
        self._false_positives_total = 0

        self._dirty = False
        self._dirty_event = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    def metrics_snapshot(self) -> IoCMatcherMetrics:
        with self._lock:
            state = self._state
            return IoCMatcherMetrics(
                indicators_loaded=dict(state.indicators_loaded) if state else {},
                bit_array_bytes=state.bit_array_bytes if state else 0,
                expected_fpr=self._matcher_cfg.fpr,
                last_rebuild_at_ns=self._last_rebuild_at_ns,
                rebuild_count=self._rebuild_count,
                rebuild_failures_total=self._rebuild_failures_total,
                checks_total=self._checks_total,
                bloom_hits_total=self._bloom_hits_total,
                confirmed_matches_total=self._confirmed_matches_total,
                false_positives_total=self._false_positives_total,
            )

    async def refresh(self) -> None:
        try:
            new_state = await self._build_state()
        except Exception:  # pragma: no cover — surfaced via failure metric
            with self._lock:
                self._rebuild_failures_total += 1
            _log.exception("ioc_matcher: rebuild failed; keeping previous state")
            return
        # CPython attribute assignment is atomic for a single object reference.
        self._state = new_state
        with self._lock:
            self._rebuild_count += 1
            self._last_rebuild_at_ns = self._clock_ns()

    async def _build_state(self) -> _MatcherState:
        enabled_types = frozenset(self._matcher_cfg.enabled_types)
        floor = self._matcher_cfg.confidence_floor
        by_type: dict[str, dict[str, Indicator]] = {}
        for feed in self._cfg.feeds:
            if not feed.enabled:
                continue
            raw = await self._store.load_state(f"taxii:snapshot:{feed.id}")
            if not raw:
                continue
            snap = msgspec.msgpack.decode(raw, type=IndicatorSnapshot)
            for ind in snap.indicators:
                if ind.type not in enabled_types:
                    continue
                if ind.confidence < floor:
                    continue
                bucket = by_type.setdefault(ind.type, {})
                bucket[ind.value] = ind

        indicators_loaded = {t: len(v) for t, v in by_type.items()}
        actual = sum(indicators_loaded.values())
        capacity = max(
            self._matcher_cfg.min_capacity,
            math.ceil(actual * self._matcher_cfg.capacity_growth_factor),
        )
        params = BloomParams(expected_items=capacity, fpr=self._matcher_cfg.fpr)
        if params.byte_size > 10 * 1024 * 1024:
            _log.warning(
                "ioc_matcher: bit array %.2f MB exceeds 10 MB budget at "
                "capacity=%d fpr=%.4f; consider raising fpr or lowering capacity",
                params.byte_size / (1024 * 1024),
                capacity,
                self._matcher_cfg.fpr,
            )
        all_values: list[str] = []
        for bucket in by_type.values():
            all_values.extend(bucket.keys())
        bloom = _BloomFilter.from_values(all_values, params)
        return _MatcherState(
            bloom=bloom,
            by_type=by_type,
            indicators_loaded=indicators_loaded,
            bit_array_bytes=params.byte_size,
        )
