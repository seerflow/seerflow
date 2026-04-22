"""EntityBaseline struct and pure update helpers."""

from __future__ import annotations

from typing import Literal

import msgspec

EntityType = Literal["user", "ip", "host", "process", "file", "domain"]


class EntityBaseline(msgspec.Struct, frozen=True, gc=False):
    """Immutable per-entity behavioral summary."""

    entity_uuid: str
    entity_type: EntityType
    first_seen_ns: int
    last_seen_ns: int
    event_count: int
    warmup_complete: bool
    hours: tuple[int, ...]
    source_ips: tuple[tuple[str, int], ...]
    volume_ema_min: float
    volume_ema_hour: float
    volume_last_ns: int
    templates: tuple[tuple[str, float], ...]


def bucket_hour_utc(timestamp_ns: int) -> int:
    """Return the UTC hour-of-day (0-23) for a nanosecond timestamp."""
    seconds = timestamp_ns // 1_000_000_000
    return int((seconds // 3600) % 24)


def update_hours(hours: tuple[int, ...], hour: int) -> tuple[int, ...]:
    """Return a new histogram with ``hour`` bucket incremented."""
    new_list = list(hours)
    new_list[hour] += 1
    return tuple(new_list)


def update_ema(*, prev: float, observed: float, alpha: float, is_first: bool) -> float:
    """Exponential moving average update.

    On the first sample there is no prior value, so we adopt the observation.
    """
    if is_first:
        return observed
    return alpha * observed + (1.0 - alpha) * prev
