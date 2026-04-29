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
import contextlib
import ipaddress
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import msgspec

from seerflow.models.indicator import IndicatorSnapshot
from seerflow.models.ioc_match import IoCMatch
from seerflow.threat_intel._bloom import BloomParams, _BloomFilter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from seerflow.config import ThreatIntelConfig
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.indicator import Indicator, IndicatorType
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

    def check(self, value: str, type_: IndicatorType) -> Indicator | None:
        with self._lock:
            self._checks_total += 1
        if type_ not in self._matcher_cfg.enabled_types:
            return None
        state = self._state
        if state is None:
            return None
        if value not in state.bloom:
            return None
        with self._lock:
            self._bloom_hits_total += 1
        ind = state.by_type.get(type_, {}).get(value)
        if ind is None:
            with self._lock:
                self._false_positives_total += 1
            return None
        with self._lock:
            self._confirmed_matches_total += 1
        return ind

    def check_many(self, values: Mapping[str, Iterable[str]]) -> tuple[IoCMatch, ...]:
        matches: list[IoCMatch] = []
        for type_, vs in values.items():
            for v in vs:
                ind = self.check(v, type_)  # type: ignore[arg-type]
                if ind is not None:
                    matches.append(self._build_match(v, type_, ind, event_id=""))
        return tuple(matches)

    def _build_match(
        self,
        value: str,
        type_: str,
        indicator: Indicator,
        *,
        event_id: str,
    ) -> IoCMatch:
        kind: str
        if type_ in ("ipv4", "ipv6"):
            kind = "ip"
        elif type_ in ("md5", "sha1", "sha256"):
            kind = "hash"
        elif type_ == "url":
            kind = "url"
        else:
            kind = "domain"
        return IoCMatch(
            value=value,
            type=type_,  # type: ignore[arg-type]
            indicator=indicator,
            event_id=event_id,
            entity_kind=kind,  # type: ignore[arg-type]
            matched_at_ns=self._clock_ns(),
        )

    def check_event(self, event: SeerflowEvent) -> tuple[IoCMatch, ...]:
        ipv4: list[str] = []
        ipv6: list[str] = []
        for raw in event.related_ips:
            with contextlib.suppress(ValueError):
                addr = ipaddress.ip_address(raw)
                if addr.version == 4:
                    ipv4.append(raw)
                else:
                    ipv6.append(raw)
        hashes_by_type: dict[str, list[str]] = {"md5": [], "sha1": [], "sha256": []}
        for raw in event.related_hashes:
            algo, _sep, hex_digest = raw.partition(":")
            if algo in hashes_by_type and hex_digest:
                hashes_by_type[algo].append(hex_digest)
        domains = list(event.related_domains)
        url = event.attributes.get("url") if isinstance(event.attributes, dict) else None
        urls = [str(url)] if isinstance(url, str) and url else []

        candidates: dict[str, list[str]] = {
            "ipv4": ipv4,
            "ipv6": ipv6,
            "domain": domains,
            "url": urls,
            **hashes_by_type,
        }
        matches: list[IoCMatch] = []
        event_id_str = str(event.event_id)
        for type_, values in candidates.items():
            for v in values:
                ind = self.check(v, type_)  # type: ignore[arg-type]
                if ind is None:
                    continue
                m = self._build_match(v, type_, ind, event_id=event_id_str)
                matches.append(m)
                if self._on_match is not None:
                    try:
                        self._on_match(m)
                    except Exception:
                        _log.exception("ioc_matcher: on_match callback raised; continuing")
        return tuple(matches)

    def on_snapshot_updated(self, _feed_id: str) -> None:
        """Sync listener — flips dirty flag, signals rebuild loop."""
        self._dirty = True
        # asyncio.Event.set() is sync-safe but only meaningful from the event
        # loop thread. The listener fires from the consumer's loop, so we are
        # already there.
        try:
            self._dirty_event.set()
        except RuntimeError:  # pragma: no cover — loop closed
            return

    async def start(self) -> None:
        if self._stopping:
            raise RuntimeError("ioc_matcher: matcher mid-shutdown")
        if self._task is not None:
            return  # already running
        await self.refresh()
        self._task = asyncio.create_task(self._run_loop(), name="ioc_matcher.loop")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (asyncio.CancelledError, TimeoutError):
            pass
        self._task = None
        self._stopping = False

    async def _run_loop(self) -> None:
        debounce_s = max(0.0, self._matcher_cfg.rebuild_debounce_ms / 1000.0)
        try:
            while True:
                await self._dirty_event.wait()
                if debounce_s > 0:
                    await asyncio.sleep(debounce_s)
                # Drain dirty flag + event before rebuild so notifications
                # arriving DURING the rebuild trigger one more pass.
                self._dirty = False
                self._dirty_event.clear()
                await self.refresh()
                if self._dirty:
                    # Loop immediately to honour late notifications.
                    continue
        except asyncio.CancelledError:
            return

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
