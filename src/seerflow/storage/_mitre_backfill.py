"""Shared MITRE-junction backfill helper (S-073).

Decodes an ``alerts.data`` msgpack blob into the (tactics, techniques,
timestamp_ns) tuple the v3 migration writes into the junction tables.

Kept storage-agnostic so both ``storage.migrations`` (SQLite) and
``storage.postgres_migrations`` (PostgreSQL) can share the same
msgpack-decode + ``format_technique`` path without copy-pasting it.
"""

from __future__ import annotations

import logging

import msgspec

from seerflow.models.alert import Alert
from seerflow.sigma.attack import format_technique

logger = logging.getLogger(__name__)


def decode_alert_for_backfill(
    blob: bytes | None,
    timestamp_ns: int,
    dedup_key: str,
) -> tuple[list[str], list[str]] | None:
    """Decode an ``alerts.data`` blob and return its MITRE rows for junction backfill.

    Returns:
        ``(tactics, formatted_techniques)`` on success — both ``list[str]``,
        with techniques run through :func:`format_technique` so the junction
        rows match the runtime ``write_alert`` path.
        ``None`` when ``blob`` is missing (caller skips the row) or when the
        blob fails to decode (caller logs a single warning per row).

    The caller is responsible for combining the returned lists with
    ``timestamp_ns`` / ``dedup_key`` into the actual insert tuples — this
    helper deliberately stays storage-agnostic so it can be reused by both
    the SQLite and PostgreSQL backfill paths.
    """
    if blob is None:
        return None
    try:
        alert = msgspec.msgpack.decode(blob, type=Alert)
    except (msgspec.DecodeError, TypeError, AttributeError):
        logger.warning(
            "mitre backfill: skipping alert %s with corrupt data blob (timestamp_ns=%d)",
            dedup_key,
            timestamp_ns,
        )
        return None
    tactics = [t for t in alert.mitre_tactics or ()]
    techniques = [format_technique(t) for t in alert.mitre_techniques or ()]
    return tactics, techniques
