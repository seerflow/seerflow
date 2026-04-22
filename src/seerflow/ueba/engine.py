"""UEBA scoring engine: composite deviation score over per-entity baselines."""

from __future__ import annotations

import msgspec


class UEBAScoreBreakdown(msgspec.Struct, frozen=True, gc=False):
    """Four-dimension deviation score + weighted composite for one event."""

    time_of_day: float
    source_novelty: float
    volume: float
    pattern_novelty: float
    composite: float
