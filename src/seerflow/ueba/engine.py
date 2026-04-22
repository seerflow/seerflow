"""UEBA scoring engine: composite deviation score over per-entity baselines."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import msgspec

from seerflow.ueba.baseline import bucket_hour_utc

if TYPE_CHECKING:
    from seerflow.config import UEBAConfig
    from seerflow.models.event import SeerflowEvent
    from seerflow.ueba.baseline import EntityBaseline


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


def _zero_breakdown() -> UEBAScoreBreakdown:
    return UEBAScoreBreakdown(
        time_of_day=0.0,
        source_novelty=0.0,
        volume=0.0,
        pattern_novelty=0.0,
        composite=0.0,
    )


class UEBAEngine:
    """Stateful wrapper that turns per-event sub-scores into a composite.

    The engine holds configuration plus two ephemeral caches (populated
    in Task 5): a per-entity-type DSPOT threshold map and a per-entity
    ``last_score`` map. It does not own the ``BaselineStore`` — callers
    supply the pre-update baseline on every ``score`` call.
    """

    def __init__(self, *, config: UEBAConfig) -> None:
        self._config = config
        # Task 5 populates these.
        self._last_score: dict[str, UEBAScoreBreakdown] = {}

    def score(
        self,
        event: SeerflowEvent,
        baseline: EntityBaseline | None,
    ) -> UEBAScoreBreakdown:
        """Return a four-dimension breakdown + composite for ``event``.

        Returns a zero-filled breakdown when ``baseline`` is ``None`` or
        has not yet completed warm-up (design decision #4).
        """
        if baseline is None or not baseline.warmup_complete:
            return _zero_breakdown()

        time_of_day = score_time_of_day(
            ts_ns=event.timestamp_ns, hours=baseline.hours
        )
        known_ips = frozenset(ip for ip, _ in baseline.source_ips)
        source_novelty = score_source_novelty(
            event_ips=event.related_ips, known=known_ips
        )
        volume = score_volume(volume_ema_min=baseline.volume_ema_min)
        pattern_novelty = score_pattern_novelty(
            template_id=event.template_id, templates=baseline.templates
        )
        weights = self._config.sub_score_weights
        composite = (
            weights.time_of_day * time_of_day
            + weights.source_novelty * source_novelty
            + weights.volume * volume
            + weights.pattern_novelty * pattern_novelty
        )
        return UEBAScoreBreakdown(
            time_of_day=time_of_day,
            source_novelty=source_novelty,
            volume=volume,
            pattern_novelty=pattern_novelty,
            composite=composite,
        )
