"""Unit tests for the Indicator and IndicatorSnapshot msgspec Structs."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.models.indicator import (
    Indicator,
    IndicatorSnapshot,
    IndicatorType,
)


def test_indicator_is_frozen_and_roundtrips_msgpack() -> None:
    ind = Indicator(
        value="1.2.3.4",
        type="ipv4",
        source_feed="otx",
        confidence=80,
        kill_chain_phases=("delivery",),
        valid_from_ns=1_700_000_000_000_000_000,
        valid_until_ns=None,
    )
    raw = msgspec.msgpack.encode(ind)
    decoded = msgspec.msgpack.decode(raw, type=Indicator)
    assert decoded == ind
    with pytest.raises(AttributeError):
        ind.value = "5.6.7.8"  # type: ignore[misc]


def test_indicator_type_is_literal() -> None:
    valid: list[IndicatorType] = [
        "ipv4",
        "ipv6",
        "domain",
        "url",
        "md5",
        "sha1",
        "sha256",
    ]
    for t in valid:
        Indicator(
            value="x",
            type=t,
            source_feed="f",
            confidence=0,
            kill_chain_phases=(),
            valid_from_ns=0,
            valid_until_ns=None,
        )


def test_indicator_snapshot_roundtrip() -> None:
    snap = IndicatorSnapshot(
        feed_id="otx",
        fetched_at_ns=42,
        indicators=(
            Indicator(
                value="evil.example",
                type="domain",
                source_feed="otx",
                confidence=50,
                kill_chain_phases=(),
                valid_from_ns=42,
                valid_until_ns=None,
            ),
        ),
        cursor="2026-04-28T00:00:00.000Z",
    )
    raw = msgspec.msgpack.encode(snap)
    decoded = msgspec.msgpack.decode(raw, type=IndicatorSnapshot)
    assert decoded == snap
