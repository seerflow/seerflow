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


from seerflow.ueba.baseline import update_source_ips, update_templates  # noqa: E402


@pytest.mark.unit
def test_update_source_ips_adds_new_ip() -> None:
    out = update_source_ips(ips=(), new_ip="10.0.0.1", now_ns=100, cap=4)
    assert out == (("10.0.0.1", 100),)


@pytest.mark.unit
def test_update_source_ips_refreshes_last_seen_for_existing() -> None:
    existing = (("10.0.0.1", 100), ("10.0.0.2", 50))
    out = update_source_ips(ips=existing, new_ip="10.0.0.2", now_ns=200, cap=4)
    assert ("10.0.0.2", 200) in out
    assert ("10.0.0.1", 100) in out
    assert len(out) == 2


@pytest.mark.unit
def test_update_source_ips_evicts_oldest_at_cap() -> None:
    existing = (
        ("10.0.0.1", 10),
        ("10.0.0.2", 20),
        ("10.0.0.3", 30),
        ("10.0.0.4", 40),
    )
    out = update_source_ips(ips=existing, new_ip="10.0.0.5", now_ns=50, cap=4)
    assert ("10.0.0.1", 10) not in out  # oldest evicted
    assert ("10.0.0.5", 50) in out
    assert len(out) == 4


@pytest.mark.unit
def test_update_templates_decays_others_and_boosts_observed() -> None:
    existing = (("t1", 0.8), ("t2", 0.4))
    out = update_templates(
        templates=existing,
        template_id="t1",
        alpha=0.5,
        top_k=4,
    )
    as_dict = dict(out)
    # t1: 0.5*1 + 0.5*0.8 = 0.9
    assert as_dict["t1"] == pytest.approx(0.9)
    # t2: decays => 0.5 * 0 + 0.5 * 0.4 = 0.2
    assert as_dict["t2"] == pytest.approx(0.2)


@pytest.mark.unit
def test_update_templates_evicts_smallest_at_top_k() -> None:
    existing = (("t1", 0.9), ("t2", 0.5), ("t3", 0.1))
    out = update_templates(
        templates=existing,
        template_id="t4",
        alpha=0.5,
        top_k=3,
    )
    as_dict = dict(out)
    assert "t3" not in as_dict  # weakest evicted to make room for t4
    assert "t4" in as_dict
    assert len(out) == 3
