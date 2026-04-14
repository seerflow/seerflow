"""In-memory ring buffer and bucketing helpers for the anomaly timeline REST endpoint.

The ring records scored events from the WS broadcast path and serves bucketed
queries for GET /api/v1/anomaly/timeline. It is intentionally ephemeral --
no persistence, no schema migration. A process restart empties it.
"""

from __future__ import annotations

from typing import Final, Literal

import msgspec

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

_ALLOWED: Final[dict[str, tuple[str, ...]]] = {
    "1h": ("1m",),
    "6h": ("1m", "5m"),
    "24h": ("5m", "15m"),
    "7d": ("15m", "1h"),
}


def allowed_resolutions(rng: str) -> tuple[str, ...]:
    """Return the allowed resolution tokens for a range."""
    return _ALLOWED[rng]


def default_resolution(rng: str) -> str:
    """Return the default (smallest allowed) resolution for a range."""
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
