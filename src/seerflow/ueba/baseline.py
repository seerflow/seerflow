"""EntityBaseline struct and pure update helpers."""

from __future__ import annotations

from typing import Literal

import msgspec

EntityType = Literal["user", "ip", "host", "process", "file", "domain"]


class EntityBaseline(msgspec.Struct, frozen=True, gc=False):
    """Immutable per-entity behavioral summary."""

    entity_uuid: str
    entity_type: EntityType
    first_seen_ns: int
    last_seen_ns: int
    event_count: int
    warmup_complete: bool
    hours: tuple[int, ...]
    source_ips: tuple[tuple[str, int], ...]
    volume_ema_min: float
    volume_ema_hour: float
    volume_last_ns: int
    templates: tuple[tuple[str, float], ...]
