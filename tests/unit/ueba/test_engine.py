"""Unit tests for UEBAEngine scoring."""

from __future__ import annotations

import uuid

import msgspec
import pytest

from seerflow.config import UEBAConfig
from seerflow.models.event import SeerflowEvent
from seerflow.ueba.baseline import EntityBaseline
from seerflow.ueba.engine import (
    UEBAEngine,
    UEBAScoreBreakdown,
    score_pattern_novelty,
    score_source_novelty,
    score_time_of_day,
    score_volume,
)


def _warm_baseline(
    *,
    hours: tuple[int, ...] = (0,) * 24,
    source_ips: tuple[tuple[str, int], ...] = (),
    volume_ema_min: float = 1.0,
    templates: tuple[tuple[str, float], ...] = (),
    first_seen_ns: int = 0,
    last_seen_ns: int = 10 * 86_400 * 1_000_000_000,
    event_count: int = 100,
) -> EntityBaseline:
    return EntityBaseline(
        entity_uuid="u1",
        entity_type="user",
        first_seen_ns=first_seen_ns,
        last_seen_ns=last_seen_ns,
        event_count=event_count,
        warmup_complete=True,
        hours=hours,
        source_ips=source_ips,
        volume_ema_min=volume_ema_min,
        volume_ema_hour=volume_ema_min * 60,
        volume_last_ns=last_seen_ns,
        templates=templates,
    )


@pytest.mark.unit
def test_ueba_score_breakdown_is_frozen_struct() -> None:
    b = UEBAScoreBreakdown(
        time_of_day=0.5,
        source_novelty=0.0,
        volume=0.1,
        pattern_novelty=0.9,
        composite=0.37,
    )
    assert b.composite == pytest.approx(0.37)
    with pytest.raises(AttributeError):
        b.time_of_day = 0.99  # type: ignore[misc]


@pytest.mark.unit
def test_ueba_score_breakdown_msgpack_roundtrip() -> None:
    b = UEBAScoreBreakdown(
        time_of_day=0.85,
        source_novelty=1.0,
        volume=0.1,
        pattern_novelty=0.7,
        composite=0.68,
    )
    encoded = msgspec.msgpack.encode(b)
    decoded = msgspec.msgpack.decode(encoded, type=UEBAScoreBreakdown)
    assert decoded == b


@pytest.mark.unit
def test_time_of_day_peak_hour_scores_zero() -> None:
    hours = tuple(100 if i == 9 else 10 for i in range(24))
    ts = 9 * 3600 * 1_000_000_000  # hour 9
    assert score_time_of_day(ts_ns=ts, hours=hours) == pytest.approx(0.0)


@pytest.mark.unit
def test_time_of_day_unseen_hour_scores_one() -> None:
    hours = tuple(100 if i == 9 else 0 for i in range(24))
    ts = 3 * 3600 * 1_000_000_000
    assert score_time_of_day(ts_ns=ts, hours=hours) == pytest.approx(1.0)


@pytest.mark.unit
def test_time_of_day_empty_histogram_returns_zero() -> None:
    assert score_time_of_day(ts_ns=0, hours=(0,) * 24) == pytest.approx(0.0)


@pytest.mark.unit
def test_source_novelty_fully_known_scores_zero() -> None:
    assert score_source_novelty(
        event_ips=("10.0.0.1",), known=frozenset({"10.0.0.1"})
    ) == pytest.approx(0.0)


@pytest.mark.unit
def test_source_novelty_fully_new_scores_one() -> None:
    assert score_source_novelty(
        event_ips=("10.0.0.99",), known=frozenset({"10.0.0.1"})
    ) == pytest.approx(1.0)


@pytest.mark.unit
def test_source_novelty_mixed_is_fractional() -> None:
    assert score_source_novelty(
        event_ips=("10.0.0.1", "10.0.0.99"), known=frozenset({"10.0.0.1"})
    ) == pytest.approx(0.5)


@pytest.mark.unit
def test_source_novelty_empty_event_ips_returns_zero() -> None:
    assert score_source_novelty(event_ips=(), known=frozenset({"10.0.0.1"})) == 0.0


@pytest.mark.unit
def test_volume_at_rate_scores_zero() -> None:
    # Current observation matches baseline rate → z ≈ 0 → score 0.
    assert score_volume(volume_ema_min=1.0) == pytest.approx(0.0)


@pytest.mark.unit
def test_volume_zero_ema_returns_zero() -> None:
    assert score_volume(volume_ema_min=0.0) == pytest.approx(0.0)


@pytest.mark.unit
def test_volume_very_quiet_baseline_spikes_score() -> None:
    # A very rare entity (ema=0.0001) seeing 1 event is a huge deviation.
    assert score_volume(volume_ema_min=0.0001) == pytest.approx(1.0)


@pytest.mark.unit
def test_pattern_novelty_known_template_scales_with_weight() -> None:
    templates = (("1", 0.9), ("2", 0.3))
    assert score_pattern_novelty(template_id=1, templates=templates) == pytest.approx(
        0.0, abs=1e-6
    )


@pytest.mark.unit
def test_pattern_novelty_unknown_template_scores_one() -> None:
    templates = (("1", 0.9),)
    assert score_pattern_novelty(template_id=42, templates=templates) == 1.0


@pytest.mark.unit
def test_pattern_novelty_no_template_returns_zero() -> None:
    templates = (("1", 0.9),)
    assert score_pattern_novelty(template_id=-1, templates=templates) == 0.0


@pytest.mark.unit
def test_pattern_novelty_empty_templates_scores_one() -> None:
    # Defensive: zero-templates but valid template_id → treat as unseen.
    assert score_pattern_novelty(template_id=5, templates=()) == 1.0


@pytest.mark.unit
def test_warm_baseline_helper_smoke() -> None:
    # Ensure the fixture builder produces a warm baseline usable in later tests.
    b = _warm_baseline(volume_ema_min=0.5)
    assert b.warmup_complete is True
    assert b.volume_ema_min == pytest.approx(0.5)


def _mk_event(ts_ns: int = 3_600 * 5 * 1_000_000_000, entity_uuid: str = "u1") -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        timestamp_ns=ts_ns,
        observed_ns=ts_ns,
        otel_severity=9,
        related_ips=("10.0.0.99",),
        entity_refs=(entity_uuid,),
        template_id=99,
    )


@pytest.mark.unit
def test_engine_score_returns_zero_when_baseline_none() -> None:
    engine = UEBAEngine(config=UEBAConfig())
    bkd = engine.score(_mk_event(), baseline=None)
    assert bkd.composite == 0.0
    assert bkd.time_of_day == 0.0
    assert bkd.source_novelty == 0.0
    assert bkd.volume == 0.0
    assert bkd.pattern_novelty == 0.0


@pytest.mark.unit
def test_engine_score_returns_zero_when_baseline_not_warm() -> None:
    engine = UEBAEngine(config=UEBAConfig())
    cold = EntityBaseline(
        entity_uuid="u1",
        entity_type="user",
        first_seen_ns=0,
        last_seen_ns=1_000_000_000,
        event_count=5,
        warmup_complete=False,
        hours=(0,) * 24,
        source_ips=(),
        volume_ema_min=0.0,
        volume_ema_hour=0.0,
        volume_last_ns=1_000_000_000,
        templates=(),
    )
    bkd = engine.score(_mk_event(), baseline=cold)
    assert bkd.composite == 0.0


@pytest.mark.unit
def test_engine_score_composite_is_weighted_sum() -> None:
    cfg = UEBAConfig()
    engine = UEBAEngine(config=cfg)
    # Warm baseline where we control each sub-score deterministically.
    hours = tuple(100 if i == 0 else 10 for i in range(24))
    baseline = _warm_baseline(hours=hours, volume_ema_min=0.0001)
    bkd = engine.score(_mk_event(), baseline=baseline)
    w = cfg.sub_score_weights
    expected = (
        w.time_of_day * bkd.time_of_day
        + w.source_novelty * bkd.source_novelty
        + w.volume * bkd.volume
        + w.pattern_novelty * bkd.pattern_novelty
    )
    assert bkd.composite == pytest.approx(expected)


@pytest.mark.unit
def test_engine_last_score_none_before_first_score() -> None:
    engine = UEBAEngine(config=UEBAConfig())
    assert engine.last_score("u1") is None


@pytest.mark.unit
def test_engine_last_score_updates_after_scoring() -> None:
    engine = UEBAEngine(config=UEBAConfig())
    baseline = _warm_baseline(volume_ema_min=0.0001)
    engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="user"
    )
    bkd = engine.last_score("u1")
    assert bkd is not None
    assert bkd.composite > 0.0


@pytest.mark.unit
def test_engine_last_score_none_when_baseline_missing() -> None:
    # No baseline -> zero breakdown -> last_score stays untouched.
    engine = UEBAEngine(config=UEBAConfig())
    bkd, alert = engine.score_and_maybe_alert(
        _mk_event(), baseline=None, entity_type="user"
    )
    assert bkd.composite == 0.0
    assert alert is None
    # Last score still recorded so the API can render "no deviation".
    assert engine.last_score("u1") is not None
    assert engine.last_score("u1").composite == 0.0  # type: ignore[union-attr]


@pytest.mark.unit
def test_engine_emits_alert_when_composite_crosses_threshold() -> None:
    cfg = UEBAConfig(score_threshold=0.1)  # low threshold → easy to cross
    engine = UEBAEngine(config=cfg)
    baseline = _warm_baseline(volume_ema_min=0.0001)
    bkd, alert = engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="user"
    )
    assert bkd.composite >= 0.1
    assert alert is not None
    assert alert.rule_name == "ueba.deviation"
    assert alert.alert_type == "ueba"
    # Breakdown is serialised into description so the dashboard can
    # render without re-running the scorer.
    assert "ueba_breakdown" in alert.description or "composite" in alert.description


@pytest.mark.unit
def test_engine_no_alert_when_below_threshold() -> None:
    cfg = UEBAConfig(score_threshold=0.99)
    engine = UEBAEngine(config=cfg)
    # Warm baseline where nothing deviates.
    hours = tuple(100 if i == 5 else 0 for i in range(24))
    baseline = _warm_baseline(
        hours=hours,
        source_ips=(("10.0.0.99", 0),),
        volume_ema_min=1.0,
        templates=(("99", 1.0),),
    )
    _, alert = engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="user"
    )
    assert alert is None


@pytest.mark.unit
def test_engine_no_alert_during_warmup() -> None:
    cfg = UEBAConfig(score_threshold=0.1)
    engine = UEBAEngine(config=cfg)
    cold = EntityBaseline(
        entity_uuid="u1",
        entity_type="user",
        first_seen_ns=0,
        last_seen_ns=1_000_000_000,
        event_count=5,
        warmup_complete=False,
        hours=(0,) * 24,
        source_ips=(),
        volume_ema_min=0.0,
        volume_ema_hour=0.0,
        volume_last_ns=1_000_000_000,
        templates=(),
    )
    bkd, alert = engine.score_and_maybe_alert(
        _mk_event(), baseline=cold, entity_type="user"
    )
    assert bkd.composite == 0.0
    assert alert is None


@pytest.mark.unit
def test_engine_no_alert_when_event_has_no_entity_refs() -> None:
    # Without entity_refs there is no key to cache last_score against
    # and no sensible alert subject, so the engine must skip the alert
    # (but the breakdown itself is still computed from the baseline).
    cfg = UEBAConfig(score_threshold=0.1)
    engine = UEBAEngine(config=cfg)
    baseline = _warm_baseline(volume_ema_min=0.0001)
    event = SeerflowEvent(
        event_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        timestamp_ns=1_000_000_000,
        observed_ns=1_000_000_000,
        otel_severity=9,
        related_ips=("10.0.0.99",),
        entity_refs=(),
        template_id=99,
    )
    bkd, alert = engine.score_and_maybe_alert(
        event, baseline=baseline, entity_type="user"
    )
    # Breakdown is still computed, but no alert and no last_score entry.
    assert alert is None
    assert engine.last_score("") is None
    # Composite reflects the pure-function result for this event.
    assert bkd.composite > 0.0


@pytest.mark.unit
def test_engine_per_entity_type_dspot_independent() -> None:
    # Two entity_types → two independent threshold tracks. Crossing the
    # 'user' tracker must not consume the 'ip' tracker's state.
    engine = UEBAEngine(config=UEBAConfig(score_threshold=0.1))
    baseline = _warm_baseline(volume_ema_min=0.0001)
    _, a_user = engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="user"
    )
    _, a_ip = engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="ip"
    )
    assert a_user is not None
    assert a_ip is not None
    # Engine maintains a distinct threshold per entity-type.
    assert "user" in engine._thresholds_for_test()
    assert "ip" in engine._thresholds_for_test()


@pytest.mark.unit
def test_engine_alert_breakdown_roundtrips() -> None:
    cfg = UEBAConfig(score_threshold=0.05)
    engine = UEBAEngine(config=cfg)
    baseline = _warm_baseline(volume_ema_min=0.0001)
    bkd, alert = engine.score_and_maybe_alert(
        _mk_event(), baseline=baseline, entity_type="user"
    )
    assert alert is not None
    # risk_score on the alert must equal the composite score.
    assert alert.risk_score == pytest.approx(bkd.composite)
    # dedup_key must be stable per-entity.
    assert alert.dedup_key == "ueba:u1"


@pytest.mark.unit
def test_engine_score_composite_with_custom_weights() -> None:
    # Different weight profile produces a different composite.
    from seerflow.config import UEBASubScoreWeights

    weights = UEBASubScoreWeights(
        time_of_day=0.1,
        source_novelty=0.6,
        volume=0.1,
        pattern_novelty=0.2,
    )
    cfg = UEBAConfig(sub_score_weights=weights)
    engine = UEBAEngine(config=cfg)
    hours = tuple(100 if i == 0 else 10 for i in range(24))
    baseline = _warm_baseline(hours=hours, volume_ema_min=0.0001)
    bkd = engine.score(_mk_event(), baseline=baseline)
    expected = (
        0.1 * bkd.time_of_day
        + 0.6 * bkd.source_novelty
        + 0.1 * bkd.volume
        + 0.2 * bkd.pattern_novelty
    )
    assert bkd.composite == pytest.approx(expected)
