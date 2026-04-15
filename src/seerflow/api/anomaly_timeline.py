"""In-memory ring buffer and bucketing helpers for the anomaly timeline REST endpoint.

The ring records scored events from the WS broadcast path and serves bucketed
queries for GET /api/v1/anomaly/timeline. It is intentionally ephemeral --
no persistence, no schema migration. A process restart empties it.

Concurrency note: ``_SourceBucket`` is intentionally mutable for O(1)
amortized append. This is safe under FastAPI's single-event-loop-per-worker
model: ``record_score`` (invoked from ``ConnectionManager.broadcast_event``)
and ``query`` (invoked from the REST handler) both run in the same asyncio
event loop. Do not call ``record_score`` from threads outside the event loop.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Final, Literal

import msgspec

# Defence-in-depth: validate source_type at ring ingestion, not just at the
# REST boundary. Events arriving from the WS broadcast path originate in
# external log sources, so malformed keys must be silently dropped before
# reaching the ring, ``SourceSelect`` options, or response ``meta.source``.
_SOURCE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

TimelineRange = Literal["1h", "6h", "24h", "7d"]
TimelineResolution = Literal["1m", "5m", "15m", "1h"]

BUCKET_NS: Final[int] = 60 * 1_000_000_000  # 1 minute -- the base bucket size.

RESOLUTION_NS: Final[dict[str, int]] = {
    "1m": 60 * 1_000_000_000,
    "5m": 5 * 60 * 1_000_000_000,
    "15m": 15 * 60 * 1_000_000_000,
    "1h": 3600 * 1_000_000_000,
}

RANGE_NS: Final[dict[str, int]] = {
    "1h": 3600 * 1_000_000_000,
    "6h": 6 * 3600 * 1_000_000_000,
    "24h": 24 * 3600 * 1_000_000_000,
    "7d": 7 * 24 * 3600 * 1_000_000_000,
}

_ALLOWED: Final[dict[TimelineRange, tuple[TimelineResolution, ...]]] = {
    "1h": ("1m",),
    "6h": ("1m", "5m"),
    "24h": ("5m", "15m"),
    "7d": ("15m", "1h"),
}


def allowed_resolutions(rng: TimelineRange) -> tuple[TimelineResolution, ...]:
    """Return the allowed resolution tokens for a range.

    Unknown keys raise ``KeyError`` by design — callers must pass a validated
    ``TimelineRange`` literal. No silent fallback.
    """
    return _ALLOWED[rng]


def default_resolution(rng: TimelineRange) -> TimelineResolution:
    """Return the default (smallest allowed) resolution for a range.

    Unknown keys raise ``KeyError`` by design — see ``allowed_resolutions``.
    """
    return _ALLOWED[rng][0]


def bucket_index(timestamp_ns: int) -> int:
    """Map a nanosecond timestamp to its 1-min bucket index (floor divide)."""
    return timestamp_ns // BUCKET_NS


class TimelineBucket(msgspec.Struct, frozen=True, gc=False):
    """One output bucket returned by the REST endpoint."""

    bucket_start_ns: int
    max_score: float | None
    avg_score: float | None
    event_count: int
    upper_threshold: float | None
    alert_count: int


@dataclass(slots=True)
class _SourceBucket:
    """Per-source aggregate inside one base (1-min) bucket."""

    max_score: float = 0.0
    sum_score: float = 0.0
    event_count: int = 0
    upper_threshold: float | None = None


@dataclass(slots=True)
class _BaseBucket:
    """One base (1-min) bucket, keyed by source."""

    bucket_start_ns: int = 0
    sources: OrderedDict[str, _SourceBucket] = field(default_factory=OrderedDict)


_DEFAULT_CAPACITY: Final[int] = 10_080  # 7 d at 1-min resolution
_DEFAULT_MAX_SOURCES: Final[int] = 50


class AnomalyTimelineRing:
    """Fixed-capacity ring buffer of base (1-min) buckets keyed by source.

    ``record_score`` merges a scored event into its bucket; ``query`` returns
    a dense series of ``TimelineBucket`` covering the requested range,
    downsampled to the requested resolution. Missing buckets are represented
    by ``event_count=0`` and carry-forward ``upper_threshold``.
    """

    def __init__(
        self,
        capacity_buckets: int = _DEFAULT_CAPACITY,
        max_sources: int = _DEFAULT_MAX_SOURCES,
    ) -> None:
        self._capacity = capacity_buckets
        self._max_sources = max_sources
        self._buckets: list[_BaseBucket | None] = [None] * capacity_buckets

    # ---- record ---------------------------------------------------------

    def record_score(
        self,
        timestamp_ns: int,
        score: float,
        upper_threshold: float | None,
        source: str,
    ) -> None:
        """Merge a scored event into its base bucket.

        Silently drops events whose ``source`` does not match
        ``_SOURCE_RE`` — the same allowlist the REST query param enforces.
        Defence-in-depth against malformed or adversarial log sources.
        """
        if not _SOURCE_RE.match(source):
            return
        idx = bucket_index(timestamp_ns)
        slot = idx % self._capacity
        existing = self._buckets[slot]
        bucket_start_ns = idx * BUCKET_NS

        if existing is None or existing.bucket_start_ns != bucket_start_ns:
            existing = _BaseBucket(bucket_start_ns=bucket_start_ns)
            self._buckets[slot] = existing

        sb = existing.sources.get(source)
        if sb is None:
            if len(existing.sources) >= self._max_sources:
                existing.sources.popitem(last=False)
            sb = _SourceBucket()
            existing.sources[source] = sb
        else:
            existing.sources.move_to_end(source)

        sb.event_count += 1
        sb.sum_score += score
        if score > sb.max_score:
            sb.max_score = score
        if upper_threshold is not None:
            sb.upper_threshold = upper_threshold

    # ---- query ----------------------------------------------------------

    def query(
        self,
        range_ns: int,
        resolution_ns: int,
        source: str | None,
        now_ns: int,
    ) -> list[TimelineBucket]:
        """Return a dense series covering ``[now_ns - range_ns, now_ns]``.

        Oldest bucket first. Gaps are filled with zero-count buckets whose
        ``upper_threshold`` carries forward the most recent non-null value.
        """
        if resolution_ns < BUCKET_NS or resolution_ns % BUCKET_NS != 0:
            msg = "resolution_ns must be a multiple of BUCKET_NS"
            raise ValueError(msg)
        if range_ns < resolution_ns or range_ns % resolution_ns != 0:
            msg = "range_ns must be a multiple of resolution_ns"
            raise ValueError(msg)

        num_out = range_ns // resolution_ns
        step = resolution_ns // BUCKET_NS

        end_idx = bucket_index(now_ns) + 1
        end_idx_aligned = (end_idx // step) * step
        start_idx = end_idx_aligned - num_out * step

        out: list[TimelineBucket] = []
        carried_threshold: float | None = None

        for i in range(num_out):
            out_bucket_start = (start_idx + i * step) * BUCKET_NS
            max_score: float | None = None
            sum_score = 0.0
            count = 0
            threshold_candidates: list[float] = []

            for j in range(step):
                base_idx = start_idx + i * step + j
                if base_idx < 0:
                    continue
                slot = base_idx % self._capacity
                b = self._buckets[slot]
                if b is None or b.bucket_start_ns != base_idx * BUCKET_NS:
                    continue

                if source is not None:
                    sb = b.sources.get(source)
                    srcs: tuple[_SourceBucket, ...] = (sb,) if sb is not None else ()
                else:
                    srcs = tuple(b.sources.values())

                for entry in srcs:
                    count += entry.event_count
                    sum_score += entry.sum_score
                    if max_score is None or entry.max_score > max_score:
                        max_score = entry.max_score
                    if entry.upper_threshold is not None:
                        threshold_candidates.append(entry.upper_threshold)

            if threshold_candidates:
                bucket_threshold: float | None = max(threshold_candidates)
                carried_threshold = bucket_threshold
            else:
                bucket_threshold = carried_threshold

            avg_score = (sum_score / count) if count else None

            out.append(
                TimelineBucket(
                    bucket_start_ns=out_bucket_start,
                    max_score=max_score,
                    avg_score=avg_score,
                    event_count=count,
                    upper_threshold=bucket_threshold,
                    alert_count=0,
                )
            )

        return out
