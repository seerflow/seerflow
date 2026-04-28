"""TAXIIFeedConsumer: scheduled poll → parse → persist for one feed."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING

import msgspec

from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.threat_intel.circuit import AuthCircuitBreaker
from seerflow.threat_intel.metrics import TAXIIMetricsRegistry
from seerflow.threat_intel.stix_parser import STIXIndicatorParser
from seerflow.utils.http import GetWithRetryError

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.config import TAXIIFeedConfig, ThreatIntelConfig
    from seerflow.storage.protocols import ModelStore
    from seerflow.threat_intel.client import TAXIIClient

_log = logging.getLogger("seerflow")


class TAXIIFeedConsumer:
    """Drives one TAXII feed: schedule, fetch, parse, persist."""

    def __init__(
        self,
        *,
        feed_config: TAXIIFeedConfig,
        defaults: ThreatIntelConfig,
        model_store: ModelStore,
        client: TAXIIClient,
        parser: STIXIndicatorParser | None = None,
        metrics: TAXIIMetricsRegistry | None = None,
        breaker: AuthCircuitBreaker | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._cfg = feed_config
        self._defaults = defaults
        self._store = model_store
        self._client = client
        self._parser = parser or STIXIndicatorParser()
        self._metrics = metrics or TAXIIMetricsRegistry()
        self._breaker = breaker or AuthCircuitBreaker()
        self._clock_ns = clock_ns

    @property
    def poll_interval_s(self) -> int:
        return self._cfg.poll_interval_s or self._defaults.default_poll_interval_s

    async def poll_once(self) -> IndicatorSnapshot:
        if not self._breaker.allow():
            return self._empty_snapshot_for_open_circuit()

        cursor_bytes = await self._store.load_state(f"taxii:cursor:{self._cfg.id}")
        added_after = cursor_bytes.decode() if cursor_bytes else None

        objects_url = self._build_objects_url()
        cap = self._defaults.max_indicators_per_feed
        collected: list[Indicator] = []
        truncated = 0
        last_added: str | None = None

        try:
            async for sdo, last in self._client.get_objects(objects_url, added_after=added_after):
                last_added = last or last_added
                if sdo is None:
                    # Cursor-only marker emitted by the client for empty pages —
                    # advance the watermark even when the page has no SDOs.
                    continue
                indicators = self._parser.parse(sdo, source_feed=self._cfg.id)
                indicators = self._filter_expired(indicators)
                indicators = self._filter_confidence(indicators)
                for ind in indicators:
                    if len(collected) >= cap:
                        truncated += 1
                        continue
                    collected.append(ind)
        except GetWithRetryError as exc:
            self._classify_failure(exc)
            return IndicatorSnapshot(
                feed_id=self._cfg.id,
                fetched_at_ns=self._clock_ns(),
                indicators=(),
                cursor=added_after,
            )

        snap = IndicatorSnapshot(
            feed_id=self._cfg.id,
            fetched_at_ns=self._clock_ns(),
            indicators=tuple(collected),
            cursor=last_added,
        )

        # Persist the snapshot+cursor pair atomically vs cancellation so a
        # SIGTERM mid-poll does not leave taxii:snapshot:* and
        # taxii:cursor:* desynchronised on disk.
        await asyncio.shield(self._persist(snap, truncated=truncated))
        self._breaker.record_success()
        self._metrics.set_circuit_open(self._cfg.id, open_=False)
        return snap

    async def run_forever(self, stop: asyncio.Event) -> None:
        jitter = random.uniform(0.0, float(self._defaults.startup_jitter_s))  # noqa: S311
        try:
            await asyncio.wait_for(stop.wait(), timeout=jitter)
            return
        except TimeoutError:
            pass
        while not stop.is_set():
            await self.poll_once()
            # AC7 — wait the configured interval ±5 % so multiple feeds do
            # not synchronise into a thundering herd after long uptimes.
            interval = float(self.poll_interval_s)
            wait_s = interval * random.uniform(0.95, 1.05) if interval > 0 else 0.0  # noqa: S311
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait_s)
                return
            except TimeoutError:
                continue

    # internals -----------------------------------------------------------

    def _empty_snapshot_for_open_circuit(self) -> IndicatorSnapshot:
        self._metrics.set_circuit_open(self._cfg.id, open_=True)
        _log.info("taxii: circuit open for feed=%s; skipping poll", self._cfg.id)
        return IndicatorSnapshot(
            feed_id=self._cfg.id,
            fetched_at_ns=self._clock_ns(),
            indicators=(),
            cursor=None,
        )

    def _build_objects_url(self) -> str:
        base = self._cfg.url.rstrip("/")
        return f"{base}/collections/{self._cfg.collection_id}/objects/"

    async def _persist(self, snap: IndicatorSnapshot, *, truncated: int) -> None:
        snap_bytes = msgspec.msgpack.encode(snap)
        await self._store.save_state(f"taxii:snapshot:{self._cfg.id}", snap_bytes)
        if snap.cursor is not None:
            await self._store.save_state(f"taxii:cursor:{self._cfg.id}", snap.cursor.encode())
        seen_by_type: dict[str, int] = {}
        for ind in snap.indicators:
            seen_by_type[ind.type] = seen_by_type.get(ind.type, 0) + 1
        self._metrics.record_poll_ok(
            self._cfg.id,
            at_ns=snap.fetched_at_ns,
            indicators_by_type=seen_by_type,
        )
        if truncated > 0:
            _log.warning(
                "taxii: feed=%s truncated %d indicators (cap=%d)",
                self._cfg.id,
                truncated,
                self._defaults.max_indicators_per_feed,
            )
            self._metrics.record_truncated(self._cfg.id, count=truncated)

    def _filter_expired(self, inds: tuple[Indicator, ...]) -> tuple[Indicator, ...]:
        grace_days = self._defaults.expired_grace_days
        if grace_days <= 0:
            return inds
        cutoff_ns = self._clock_ns() - grace_days * 86_400 * 1_000_000_000
        return tuple(
            ind for ind in inds if ind.valid_until_ns is None or ind.valid_until_ns >= cutoff_ns
        )

    def _filter_confidence(self, inds: tuple[Indicator, ...]) -> tuple[Indicator, ...]:
        floor = self._cfg.confidence_floor
        if floor <= 0:
            return inds
        return tuple(ind for ind in inds if ind.confidence >= floor)

    def _classify_failure(self, exc: GetWithRetryError) -> None:
        # Branch on the typed HTTP status, not on substring matching the
        # exception message — the message format is implementation detail.
        if exc.status in (401, 403):
            self._breaker.record_failure()
            self._metrics.record_poll_failed(self._cfg.id, auth=True)
            self._metrics.set_circuit_open(self._cfg.id, open_=self._breaker.is_open())
            _log.error("taxii: auth failure feed=%s: %s", self._cfg.id, exc)
        else:
            self._metrics.record_poll_failed(self._cfg.id, auth=False)
            _log.warning("taxii: poll failed feed=%s: %s", self._cfg.id, exc)
