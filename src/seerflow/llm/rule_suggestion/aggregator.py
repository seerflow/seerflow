"""TP-feedback aggregator wrapper for the rule-suggestion service.

The real aggregation runs in storage (single SQL ``GROUP BY``), so the
``AlertStore.aggregate_tp_feedback`` Protocol method does all the heavy
lifting. This module exposes two surfaces:

* ``PatternFeedbackRow`` — the immutable row returned by the storage
  layer and consumed by every downstream caller (route handler, prompt
  builder, service). Defined here (rather than in ``storage.protocols``)
  so the rule-suggestion subpackage owns the data shape; ``protocols``
  imports it back to declare the Protocol method.
* ``count_pattern_tps`` — a thin async wrapper that defaults ``min_tp``
  to the FR-066 acceptance threshold (3) and clips
  ``contributing_alert_ids`` to ``_MAX_CONTRIBUTING_ALERT_IDS=16`` so the
  prompt budget stays bounded even if a future storage implementation
  forgets the cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.storage.protocols import AlertStore


# Hard cap on the per-pattern ID list that ships through to the LLM prompt.
# Sixteen IDs * 36-byte UUID + separators stays well under any sensible
# prompt budget. The storage layer is expected to return at most this many
# (newest first); the wrapper clips defensively so a future backend
# regression cannot blow the LLM context window.
_MAX_CONTRIBUTING_ALERT_IDS = 16

# Storage-side row scan ceiling. The SQL ``LIMIT`` protects long-running
# deployments where the feedback log grows into the millions; the result is
# conservative (only patterns confirmed within the scanned slice) rather
# than wrong.
_AGGREGATOR_SCAN_LIMIT = 50_000

# Default ``min_tp`` mirrors the FR-066 acceptance criterion.
_DEFAULT_MIN_TP = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class PatternFeedbackRow:
    """One row of the TP-feedback aggregate, keyed by pattern.

    Attributes:
        pattern_key: ``"{alert_type}:{rule_name}:{entity_type}"`` (sanitised).
        tp_count: Number of distinct alerts with a latest TP verdict for
            this pattern, within the scan limit / time window.
        most_recent_tp_ns: Wall-clock nanoseconds of the most recent TP
            feedback contributing to ``tp_count``. Used for ordering and
            cache-staleness checks.
        contributing_alert_ids: Up to 16 alert IDs, newest TP first, that
            the prompt builder uses to fetch sample alerts.
    """

    pattern_key: str
    tp_count: int
    most_recent_tp_ns: int
    contributing_alert_ids: tuple[str, ...] = ()


async def count_pattern_tps(
    alert_store: AlertStore,
    *,
    min_tp: int = _DEFAULT_MIN_TP,
    window_ns: int | None = None,
    now_ns: int | None = None,
    limit: int = _AGGREGATOR_SCAN_LIMIT,
) -> tuple[PatternFeedbackRow, ...]:
    """Return eligible patterns from the alert-store feedback aggregator.

    The function delegates to ``alert_store.aggregate_tp_feedback`` (which
    runs a single SQL query in SQLite / PostgreSQL) and applies a defensive
    cap of ``_MAX_CONTRIBUTING_ALERT_IDS`` on each row's
    ``contributing_alert_ids`` tuple.

    Args:
        alert_store: An object satisfying the ``AlertStore`` Protocol.
        min_tp: Minimum TP count to be considered an "eligible pattern"
            (default 3, mirroring FR-066). Storage filters; the wrapper
            does not re-check.
        window_ns: If provided, consider only TP events with
            ``submitted_at_ns >= now_ns - window_ns``. ``None`` (default)
            means all-time.
        now_ns: Reference wall-clock used by ``window_ns``. Storage layer
            falls back to its own clock when ``None``.
        limit: Storage scan ceiling. Defaults to ``_AGGREGATOR_SCAN_LIMIT``.

    Returns:
        Tuple of ``PatternFeedbackRow`` instances. Order matches the
        storage layer (typically ``tp_count DESC, most_recent_tp_ns DESC``).
    """
    rows = await alert_store.aggregate_tp_feedback(
        min_tp=min_tp,
        window_ns=window_ns,
        now_ns=now_ns,
        limit=limit,
    )
    if not rows:
        return ()
    # Defensive cap: clip ``contributing_alert_ids`` per row. The storage
    # layer is expected to honour this already, but the wrapper is the
    # single chokepoint for downstream consumers, so we never expose more
    # IDs than the prompt budget can absorb.
    clipped = tuple(
        PatternFeedbackRow(
            pattern_key=row.pattern_key,
            tp_count=row.tp_count,
            most_recent_tp_ns=row.most_recent_tp_ns,
            contributing_alert_ids=row.contributing_alert_ids[:_MAX_CONTRIBUTING_ALERT_IDS],
        )
        for row in rows
    )
    return clipped
