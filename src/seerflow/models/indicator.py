"""STIX/TAXII threat-intelligence indicator data model.

These are the persistence shapes consumed by S-068 (Bloom filter) and
S-069 (alert enrichment). The msgspec Structs are frozen and ``gc=False``
to match every other Seerflow model.
"""

from __future__ import annotations

from typing import Literal

import msgspec

IndicatorType = Literal["ipv4", "ipv6", "domain", "url", "md5", "sha1", "sha256"]


class Indicator(msgspec.Struct, frozen=True, gc=False):
    """One observable extracted from a STIX 2.1 indicator SDO."""

    value: str
    type: IndicatorType
    source_feed: str
    confidence: int
    kill_chain_phases: tuple[str, ...]
    valid_from_ns: int
    valid_until_ns: int | None


class IndicatorSnapshot(msgspec.Struct, frozen=True, gc=False):
    """Result of one TAXII poll, persisted under ``taxii:snapshot:<feed_id>``."""

    feed_id: str
    fetched_at_ns: int
    indicators: tuple[Indicator, ...]
    cursor: str | None
