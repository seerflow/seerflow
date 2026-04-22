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
