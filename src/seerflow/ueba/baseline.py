"""EntityBaseline struct and pure update helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import msgspec

if TYPE_CHECKING:
    from seerflow.models.event import SeerflowEvent

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


class UEBAParams(msgspec.Struct, frozen=True):
    """Tunable knobs for :func:`apply_event`."""

    alpha: float
    source_ip_cap: int
    template_top_k: int
    warmup_days: int
    warmup_min_events: int


_NS_PER_DAY = 86_400 * 1_000_000_000


def apply_event(
    *,
    baseline: EntityBaseline | None,
    entity_uuid: str,
    entity_type: EntityType,
    event: SeerflowEvent,
    params: UEBAParams,
) -> EntityBaseline:
    """Return a new EntityBaseline reflecting ``event``."""
    ts_ns = event.timestamp_ns
    is_first = baseline is None
    prev_hours = baseline.hours if baseline else tuple([0] * 24)
    prev_ips = baseline.source_ips if baseline else ()
    prev_templates = baseline.templates if baseline else ()
    prev_ema_min = baseline.volume_ema_min if baseline else 0.0
    prev_ema_hour = baseline.volume_ema_hour if baseline else 0.0

    hours = update_hours(prev_hours, bucket_hour_utc(ts_ns))

    ips = prev_ips
    for ip in event.related_ips:
        ips = update_source_ips(
            ips=ips,
            new_ip=ip,
            now_ns=ts_ns,
            cap=params.source_ip_cap,
        )

    templates = prev_templates
    # SeerflowEvent.template_id is int; -1 is the no-template sentinel.
    if event.template_id != -1:
        templates = update_templates(
            templates=templates,
            template_id=str(event.template_id),
            alpha=params.alpha,
            top_k=params.template_top_k,
        )

    # EMAs: observe "1 event in the last minute/hour" whenever an event arrives.
    ema_min = update_ema(
        prev=prev_ema_min,
        observed=1.0,
        alpha=params.alpha,
        is_first=is_first,
    )
    ema_hour = update_ema(
        prev=prev_ema_hour,
        observed=1.0,
        alpha=params.alpha,
        is_first=is_first,
    )

    first_seen_ns = baseline.first_seen_ns if baseline else ts_ns
    last_seen_ns = max(baseline.last_seen_ns if baseline else ts_ns, ts_ns)
    event_count = (baseline.event_count if baseline else 0) + 1

    span_ns = last_seen_ns - first_seen_ns
    warmup_complete = (
        span_ns >= params.warmup_days * _NS_PER_DAY
        and event_count >= params.warmup_min_events
    )
    # Latch once true.
    if baseline and baseline.warmup_complete:
        warmup_complete = True

    return EntityBaseline(
        entity_uuid=entity_uuid,
        entity_type=entity_type,
        first_seen_ns=first_seen_ns,
        last_seen_ns=last_seen_ns,
        event_count=event_count,
        warmup_complete=warmup_complete,
        hours=hours,
        source_ips=ips,
        volume_ema_min=ema_min,
        volume_ema_hour=ema_hour,
        volume_last_ns=ts_ns,
        templates=templates,
    )
