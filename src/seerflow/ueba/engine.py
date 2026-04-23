"""UEBA scoring engine: composite deviation score over per-entity baselines."""

from __future__ import annotations

import math
import uuid
from typing import TYPE_CHECKING

import msgspec

from seerflow.detection.threshold import DSpotThreshold
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.ueba.baseline import bucket_hour_utc

if TYPE_CHECKING:
    from seerflow.config import UEBAConfig
    from seerflow.models._types import EntityType
    from seerflow.models.event import SeerflowEvent
    from seerflow.ueba.baseline import EntityBaseline


# DSPOT calibration parameters for per-entity-type thresholds.
# Intentionally module-level rather than UEBAConfig fields: these are the
# library's calibration knobs (how DSPOT learns its quantile), not policy
# knobs operators tune per deployment. Kept as named constants so reviewers
# and future readers can find them without grepping the engine.
_DSPOT_CALIBRATION_WINDOW = 1000
_DSPOT_RISK_LEVEL = 0.0001
_DSPOT_INITIAL_PERCENTILE = 98


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


def score_source_novelty(*, event_ips: tuple[str, ...], known: frozenset[str]) -> float:
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
    to ``[0, 1]`` — 3-sigma maps to 1.0.

    Zero EMA returns 0.0 (brand-new entity / post-eviction guard).
    """
    if volume_ema_min <= 0.0:
        return 0.0
    lam = max(volume_ema_min, 1e-6)
    z = (1.0 - lam) / math.sqrt(lam)
    return min(1.0, max(0.0, z / 3.0))


def score_pattern_novelty(*, template_id: int, templates: tuple[tuple[str, float], ...]) -> float:
    """Return the template-pattern novelty score.

    ``template_id == -1`` (no-template sentinel) → 0.0. A template absent
    from the baseline's top-K → 1.0. Otherwise scale by
    ``1 - weight / max_weight`` so the peak template scores 0.0.
    """
    if template_id == -1:
        return 0.0
    key = str(template_id)
    # Templates are capped at template_top_k (default 32); linear scan
    # avoids the per-event dict allocation flagged by the python-review.
    matched: float | None = None
    max_w = 0.0
    for k, w in templates:
        if w > max_w:
            max_w = w
        if k == key:
            matched = w
    if matched is None:
        return 1.0
    if max_w <= 0.0:
        return 0.0
    return 1.0 - matched / max_w


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

    The engine holds configuration plus two ephemeral caches:

    - ``_thresholds``: per-entity-type :class:`DSpotThreshold` instances
      (design decision #2). Cold-start threshold comes from
      ``config.score_threshold``; DSPOT takes over after its calibration
      window fills.
    - ``_last_score``: per-entity ``UEBAScoreBreakdown`` cache (design
      decision #3). Ephemeral — dropped on restart.

    The engine does not own the :class:`BaselineStore` — callers supply
    the pre-update baseline on every ``score`` call.
    """

    def __init__(self, *, config: UEBAConfig) -> None:
        self._config = config
        self._last_score: dict[str, UEBAScoreBreakdown] = {}
        self._thresholds: dict[str, DSpotThreshold] = {}

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

        time_of_day = score_time_of_day(ts_ns=event.timestamp_ns, hours=baseline.hours)
        known_ips = frozenset(ip for ip, _ in baseline.source_ips)
        source_novelty = score_source_novelty(event_ips=event.related_ips, known=known_ips)
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

    def last_score(self, entity_uuid: str) -> UEBAScoreBreakdown | None:
        """Return the most recent breakdown scored for ``entity_uuid``.

        Returns ``None`` before the engine has scored any event for this
        entity or after a process restart (cache is ephemeral by design).
        """
        return self._last_score.get(entity_uuid)

    def _thresholds_for_test(self) -> dict[str, DSpotThreshold]:
        """Expose the internal threshold map for unit tests only."""
        return self._thresholds

    def _seed_last_score_for_test(
        self,
        entity_uuid: str,
        breakdown: UEBAScoreBreakdown,
    ) -> None:
        """Seed ``_last_score`` without driving a real event through the pipeline.

        Tests only — keeps assertion-grade breakdowns exact while avoiding
        direct mutation of the private cache dict.
        """
        self._last_score[entity_uuid] = breakdown

    def _threshold_for(self, entity_type: str) -> DSpotThreshold:
        t = self._thresholds.get(entity_type)
        if t is None:
            t = DSpotThreshold(
                calibration_window=_DSPOT_CALIBRATION_WINDOW,
                risk_level=_DSPOT_RISK_LEVEL,
                initial_percentile=_DSPOT_INITIAL_PERCENTILE,
            )
            self._thresholds[entity_type] = t
        return t

    def _current_threshold(self, dspot: DSpotThreshold) -> float:
        """Return the effective alert cut-off score.

        Pre-calibration → config cold-start value. Post-calibration →
        DSPOT's adaptive upper quantile (bounded below by the config
        value so a low-volatility channel can't fire on noise).
        """
        if not dspot.is_calibrated:
            return self._config.score_threshold
        return max(self._config.score_threshold, dspot.threshold)

    def score_and_maybe_alert(
        self,
        event: SeerflowEvent,
        baseline: EntityBaseline | None,
        *,
        entity_type: EntityType,
    ) -> tuple[UEBAScoreBreakdown, Alert | None]:
        """Score ``event``, cache the breakdown, emit an Alert on crossing.

        Returns ``(breakdown, None)`` when there is no entity to key on,
        when the baseline is absent/warming up, or when the composite is
        below the per-entity-type threshold. Returns ``(breakdown, alert)``
        otherwise. The breakdown is also recorded in ``last_score`` keyed
        by the first entity UUID.
        """
        breakdown = self.score(event, baseline)
        if not event.entity_refs:
            return breakdown, None
        entity_uuid = event.entity_refs[0]
        self._last_score[entity_uuid] = breakdown
        # No alerts during warm-up / when baseline is missing.
        if breakdown.composite <= 0.0:
            return breakdown, None
        threshold = self._threshold_for(entity_type)
        # Feed into DSPOT for future calibration. We DO NOT consult
        # threshold.update()'s is_anomaly flag — our trigger is the
        # config cold-start value until DSPOT finishes calibrating.
        threshold.update(breakdown.composite)
        cutoff = self._current_threshold(threshold)
        if breakdown.composite < cutoff:
            return breakdown, None
        alert = _build_alert(
            event=event,
            entity_uuid=entity_uuid,
            entity_type=entity_type,
            breakdown=breakdown,
        )
        return breakdown, alert


def _build_alert(
    *,
    event: SeerflowEvent,
    entity_uuid: str,
    entity_type: EntityType,
    breakdown: UEBAScoreBreakdown,
) -> Alert:
    """Construct a ``ueba.deviation`` Alert with the breakdown encoded in place.

    The Alert struct does not carry a ``context`` dict (S-064 era), so
    the breakdown is serialised into ``description`` as an msgpack-json
    blob. Downstream consumers decode via :func:`_breakdown_from_description`
    if they need the structured payload.
    """
    description = _encode_breakdown_description(breakdown)
    # Map composite [0, 1] → severity 1..6 (INFORMATIONAL..FATAL).
    sev_value = min(6, max(1, 1 + int(breakdown.composite * 6)))
    severity = SeverityLevel(sev_value)
    return Alert(
        alert_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"ueba:{entity_uuid}:{event.timestamp_ns}",
            )
        ),
        alert_type="ueba",
        timestamp_ns=event.timestamp_ns,
        severity_id=severity,
        rule_name="ueba.deviation",
        description=description,
        entity_uuid=entity_uuid,
        entity_value="",
        entity_type=entity_type,
        contributing_events=(event.event_id,),
        risk_score=breakdown.composite,
        dedup_key=f"ueba:{entity_uuid}",
    )


def _encode_breakdown_description(breakdown: UEBAScoreBreakdown) -> str:
    """Serialise a breakdown into the Alert description.

    Format: ``"UEBA deviation composite=0.68 ueba_breakdown={...json...}"``.
    The ``ueba_breakdown=`` prefix gives dashboards + log-scrapers a
    stable parse key without adding an Alert struct field (avoids the
    msgpack compatibility break flagged in the design spec).
    """
    payload = msgspec.to_builtins(breakdown)
    encoded = msgspec.json.encode(payload).decode("utf-8")
    return f"UEBA deviation composite={breakdown.composite:.4f} ueba_breakdown={encoded}"
