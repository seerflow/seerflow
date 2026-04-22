"""UEBA scoring engine: composite deviation score over per-entity baselines."""

from __future__ import annotations

import math

import msgspec

from seerflow.ueba.baseline import bucket_hour_utc


class UEBAScoreBreakdown(msgspec.Struct, frozen=True, gc=False):
    """Four-dimension deviation score + weighted composite for one event."""

    time_of_day: float
    source_novelty: float
    volume: float
    pattern_novelty: float
    composite: float


def score_time_of_day(*, ts_ns: int, hours: tuple[int, ...]) -> float:
    """Return the time-of-day deviation score for ``ts_ns``.

    Max-normalised histogram. Peak hour scores 0.0; a completely unseen
    hour scores 1.0. Returns 0.0 for an all-zero histogram (defensive —
    in practice callers gate on ``warmup_complete``).
    """
    max_count = max(hours)
    if max_count == 0:
        return 0.0
    hour = bucket_hour_utc(ts_ns)
    return max(0.0, 1.0 - hours[hour] / max_count)


def score_source_novelty(
    *, event_ips: tuple[str, ...], known: frozenset[str]
) -> float:
    """Return the source-IP novelty score.

    1.0 when every event IP is new; 0.0 when every event IP is already
    in the baseline's known set. Fractional for mixed. Empty event IP
    tuple → 0.0 (no signal).
    """
    if not event_ips:
        return 0.0
    matches = sum(ip in known for ip in event_ips)
    return 1.0 - matches / len(event_ips)


def score_volume(*, volume_ema_min: float) -> float:
    """Return the volume-deviation score using a Poisson z approximation.

    Uses the single-event observation rate of 1.0 per minute against the
    baseline EMA. ``z = (1 - lam) / sqrt(lam)``, then ``z/3`` clipped
    to ``[0, 1]`` — 3σ maps to 1.0.

    Zero EMA returns 0.0 (brand-new entity / post-eviction guard).
    """
    if volume_ema_min <= 0.0:
        return 0.0
    lam = max(volume_ema_min, 1e-6)
    z = (1.0 - lam) / math.sqrt(lam)
    return min(1.0, max(0.0, z / 3.0))


def score_pattern_novelty(
    *, template_id: int, templates: tuple[tuple[str, float], ...]
) -> float:
    """Return the template-pattern novelty score.

    ``template_id == -1`` (no-template sentinel) → 0.0. A template absent
    from the baseline's top-K → 1.0. Otherwise scale by
    ``1 - weight / max_weight`` so the peak template scores 0.0.
    """
    if template_id == -1:
        return 0.0
    key = str(template_id)
    tmpl = dict(templates)
    if key not in tmpl:
        return 1.0
    max_w = max(tmpl.values(), default=1.0)
    if max_w <= 0.0:
        return 0.0
    return 1.0 - tmpl[key] / max_w
