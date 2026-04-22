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


def update_source_ips(
    *,
    ips: tuple[tuple[str, int], ...],
    new_ip: str,
    now_ns: int,
    cap: int,
) -> tuple[tuple[str, int], ...]:
    """Return a new bounded source-IP list.

    - If ``new_ip`` already exists, refresh its ``last_seen_ns``.
    - If adding would exceed ``cap``, evict the entry with the smallest
      ``last_seen_ns`` (oldest-seen IP).
    """
    as_dict: dict[str, int] = dict(ips)
    as_dict[new_ip] = now_ns
    if len(as_dict) > cap:
        # Evict lowest last_seen_ns first.
        ordered = sorted(as_dict.items(), key=lambda kv: kv[1])
        as_dict = dict(ordered[len(ordered) - cap :])
    return tuple(as_dict.items())


def update_templates(
    *,
    templates: tuple[tuple[str, float], ...],
    template_id: str,
    alpha: float,
    top_k: int,
) -> tuple[tuple[str, float], ...]:
    """Return a new top-K template distribution.

    - Decay every existing entry by ``(1 - alpha)``.
    - Boost the observed template by ``alpha * 1.0`` (EMA with observation 1.0).
    - Cap at ``top_k`` by evicting entries with the smallest weight.
    """
    decayed: dict[str, float] = {tid: (1.0 - alpha) * w for tid, w in templates}
    decayed[template_id] = decayed.get(template_id, 0.0) + alpha * 1.0
    if len(decayed) > top_k:
        ordered = sorted(decayed.items(), key=lambda kv: kv[1], reverse=True)
        decayed = dict(ordered[:top_k])
    return tuple(decayed.items())
