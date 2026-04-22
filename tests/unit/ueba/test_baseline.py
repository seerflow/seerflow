"""Unit tests for EntityBaseline struct."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.ueba.baseline import EntityBaseline


@pytest.mark.unit
def test_entity_baseline_is_frozen_struct() -> None:
    b = EntityBaseline(
        entity_uuid="11111111-1111-5111-8111-111111111111",
        entity_type="user",
        first_seen_ns=1_000,
        last_seen_ns=1_000,
        event_count=1,
        warmup_complete=False,
        hours=tuple([0] * 24),
        source_ips=(),
        volume_ema_min=0.0,
        volume_ema_hour=0.0,
        volume_last_ns=1_000,
        templates=(),
    )
    assert b.entity_uuid == "11111111-1111-5111-8111-111111111111"
    assert len(b.hours) == 24
    with pytest.raises(AttributeError):
        b.event_count = 2  # type: ignore[misc]


@pytest.mark.unit
def test_entity_baseline_msgpack_roundtrip() -> None:
    b = EntityBaseline(
        entity_uuid="u1",
        entity_type="user",
        first_seen_ns=1,
        last_seen_ns=2,
        event_count=5,
        warmup_complete=True,
        hours=tuple([1] * 24),
        source_ips=(("10.0.0.1", 2),),
        volume_ema_min=1.5,
        volume_ema_hour=0.5,
        volume_last_ns=2,
        templates=(("t42", 0.9),),
    )
    encoded = msgspec.msgpack.encode(b)
    decoded = msgspec.msgpack.decode(encoded, type=EntityBaseline)
    assert decoded == b


from seerflow.ueba.baseline import (  # noqa: E402
    bucket_hour_utc,
    update_ema,
    update_hours,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ns", "expected_hour"),
    [
        (0, 0),  # 1970-01-01 00:00:00 UTC
        (3_600 * 1_000_000_000, 1),  # +1 hour
        (86_400 * 1_000_000_000, 0),  # next day same hour
        (3_600 * 3 * 1_000_000_000 + 59 * 60 * 1_000_000_000, 3),
    ],
)
def test_bucket_hour_utc(ns: int, expected_hour: int) -> None:
    assert bucket_hour_utc(ns) == expected_hour


@pytest.mark.unit
def test_update_hours_increments_bucket() -> None:
    h = tuple([0] * 24)
    out = update_hours(h, bucket_hour_utc(3_600 * 5 * 1_000_000_000))
    assert out[5] == 1
    assert sum(out) == 1
    # Immutability: input unchanged.
    assert h == tuple([0] * 24)


@pytest.mark.unit
def test_update_ema_first_sample_equals_observed() -> None:
    assert update_ema(prev=0.0, observed=10.0, alpha=0.05, is_first=True) == 10.0


@pytest.mark.unit
def test_update_ema_subsequent_blends() -> None:
    # alpha=0.5, prev=10, observed=20  -> 0.5*20 + 0.5*10 = 15
    assert update_ema(prev=10.0, observed=20.0, alpha=0.5, is_first=False) == 15.0
