"""Unit tests for the IoCMatch model."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.models.indicator import Indicator
from seerflow.models.ioc_match import IoCMatch


def _ind() -> Indicator:
    return Indicator(
        value="1.2.3.4",
        type="ipv4",
        source_feed="otx",
        confidence=80,
        kill_chain_phases=("delivery",),
        valid_from_ns=1_700_000_000_000_000_000,
        valid_until_ns=None,
    )


def test_ioc_match_roundtrip_msgpack() -> None:
    m = IoCMatch(
        value="1.2.3.4",
        type="ipv4",
        indicator=_ind(),
        event_id="11111111-2222-3333-4444-555555555555",
        entity_kind="ip",
        matched_at_ns=42,
    )
    raw = msgspec.msgpack.encode(m)
    decoded = msgspec.msgpack.decode(raw, type=IoCMatch)
    assert decoded == m


def test_ioc_match_is_frozen() -> None:
    m = IoCMatch(
        value="1.2.3.4",
        type="ipv4",
        indicator=_ind(),
        event_id="x",
        entity_kind="ip",
        matched_at_ns=0,
    )
    with pytest.raises(AttributeError):
        m.value = "5.6.7.8"  # type: ignore[misc]
