"""IoCMatch — emitted by S-068's IoCMatcher, consumed by S-069's alert pipeline."""

from __future__ import annotations

from typing import Literal

import msgspec

from seerflow.models.indicator import Indicator, IndicatorType


class IoCMatch(msgspec.Struct, frozen=True, gc=False):
    """One confirmed match between a SeerflowEvent surface value and a TI indicator."""

    value: str
    type: IndicatorType
    indicator: Indicator
    event_id: str
    entity_kind: Literal["ip", "domain", "url", "hash"]
    matched_at_ns: int
