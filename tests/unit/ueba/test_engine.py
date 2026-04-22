"""Unit tests for UEBAEngine scoring."""

from __future__ import annotations

import msgspec
import pytest

from seerflow.ueba.engine import UEBAScoreBreakdown


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
