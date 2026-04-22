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


class _PriorState(msgspec.Struct, frozen=True, gc=False):
    """Snapshot of prior-baseline fields used by :func:`apply_event`."""

    is_first: bool
    hours: tuple[int, ...]
    ips: tuple[tuple[str, int], ...]
    templates: tuple[tuple[str, float], ...]
    ema_min: float
    ema_hour: float
    first_seen_ns: int
    last_seen_ns: int
    event_count: int
    warmup_latched: bool


def _prior_state(baseline: EntityBaseline | None, ts_ns: int) -> _PriorState:
    """Extract starting values from ``baseline`` (or defaults when absent)."""
    if baseline is None:
        return _PriorState(
            is_first=True,
            hours=tuple([0] * 24),
            ips=(),
            templates=(),
            ema_min=0.0,
            ema_hour=0.0,
            first_seen_ns=ts_ns,
            last_seen_ns=ts_ns,
            event_count=0,
            warmup_latched=False,
        )
    return _PriorState(
        is_first=False,
        hours=baseline.hours,
        ips=baseline.source_ips,
        templates=baseline.templates,
        ema_min=baseline.volume_ema_min,
        ema_hour=baseline.volume_ema_hour,
        first_seen_ns=baseline.first_seen_ns,
        last_seen_ns=baseline.last_seen_ns,
        event_count=baseline.event_count,
        warmup_latched=baseline.warmup_complete,
    )


def _compute_warmup(
    *,
    prev_latched: bool,
    span_ns: int,
    event_count: int,
    params: UEBAParams,
) -> bool:
    """Return the latched warmup flag, honouring the once-true rule."""
    if prev_latched:
        return True
    return span_ns >= params.warmup_days * _NS_PER_DAY and event_count >= params.warmup_min_events


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
    prev = _prior_state(baseline, ts_ns)

    hours = update_hours(prev.hours, bucket_hour_utc(ts_ns))
    ips = prev.ips
    for ip in event.related_ips:
        ips = update_source_ips(ips=ips, new_ip=ip, now_ns=ts_ns, cap=params.source_ip_cap)
    # SeerflowEvent.template_id is int; -1 is the no-template sentinel.
    templates = (
        update_templates(
            templates=prev.templates,
            template_id=str(event.template_id),
            alpha=params.alpha,
            top_k=params.template_top_k,
        )
        if event.template_id != -1
        else prev.templates
    )
    # EMAs: observe "1 event in the last minute/hour" whenever an event arrives.
    ema_min = update_ema(
        prev=prev.ema_min, observed=1.0, alpha=params.alpha, is_first=prev.is_first
    )
    ema_hour = update_ema(
        prev=prev.ema_hour, observed=1.0, alpha=params.alpha, is_first=prev.is_first
    )

    last_seen_ns = max(prev.last_seen_ns, ts_ns)
    event_count = prev.event_count + 1
    warmup_complete = _compute_warmup(
        prev_latched=prev.warmup_latched,
        span_ns=last_seen_ns - prev.first_seen_ns,
        event_count=event_count,
        params=params,
    )

    return EntityBaseline(
        entity_uuid=entity_uuid,
        entity_type=entity_type,
        first_seen_ns=prev.first_seen_ns,
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
