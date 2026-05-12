"""Entity baseline context for the explanation prompt (S-071).

Decouples the prompt builder from the UEBA ``BaselineStore`` so the prompt
function stays pure and the loader can be tested independently.

The loader degrades gracefully:

- ``BaselineStore is None`` (UEBA disabled) → context with
  ``baseline_summary=None``.
- ``BaselineStore.get(...)`` returns ``None`` (entity unknown) → same.
- Otherwise → a short human-readable string summarising the baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.ueba.baseline import EntityBaseline
    from seerflow.ueba.store import BaselineStore


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityBaselineContext:
    """Light immutable context attached to the prompt's ENTITY CONTEXT section.

    ``baseline_summary`` is ``None`` when no baseline exists for the entity
    (either UEBA disabled or the entity has not warmed up yet).
    """

    entity_uuid: str
    entity_value: str
    entity_type: str
    baseline_summary: str | None


def _top_hours(hours: tuple[int, ...], top_n: int = 3) -> tuple[int, ...]:
    """Return the ``top_n`` busiest hour buckets (descending by count)."""
    indexed = sorted(enumerate(hours), key=lambda kv: kv[1], reverse=True)
    return tuple(h for h, count in indexed[:top_n] if count > 0)


def _format_baseline(baseline: EntityBaseline) -> str:
    """Compose a one-line summary string from an ``EntityBaseline``."""
    last_seen_iso = datetime.fromtimestamp(
        baseline.last_seen_ns / 1_000_000_000,
        tz=UTC,
    ).isoformat(timespec="seconds")
    top = _top_hours(baseline.hours)
    busiest = ",".join(f"{h:02d}h" for h in top) if top else "n/a"
    return (
        f"events={baseline.event_count} "
        f"busiest_hours_utc={busiest} "
        f"volume_ema_min={baseline.volume_ema_min:.2f} "
        f"last_seen_utc={last_seen_iso} "
        f"warmup_complete={baseline.warmup_complete}"
    )


def load_entity_baseline_context(
    *,
    entity_uuid: str,
    entity_value: str,
    entity_type: str,
    baseline_store: BaselineStore | None,
) -> EntityBaselineContext:
    """Load the baseline-derived context. ``None`` baseline → no summary.

    The loader never raises; it falls back to ``baseline_summary=None`` if
    the store returns nothing or the per-entity record is missing.
    """
    summary: str | None = None
    if baseline_store is not None:
        baseline = baseline_store.get(entity_uuid)
        if baseline is not None:
            summary = _format_baseline(baseline)
    return EntityBaselineContext(
        entity_uuid=entity_uuid,
        entity_value=entity_value,
        entity_type=entity_type,
        baseline_summary=summary,
    )
