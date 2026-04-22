"""Unit tests for UEBAEngine scoring."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.ueba.baseline import EntityBaseline
from seerflow.ueba.engine import (
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
