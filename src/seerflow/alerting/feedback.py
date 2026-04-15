"""TP/FP feedback processing — storage update + DSPOT threshold adjustment."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.models._types import FeedbackType
    from seerflow.models.alert import Alert
    from seerflow.storage.protocols import AlertStore

_log = logging.getLogger("seerflow")

_FP_THRESHOLD_FACTOR = 1.05  # Multiplicative increase per FP


def _derive_source_key(alert: Alert) -> str:
    """Extract the DSPOT source key from an alert's dedup_key.

    HST alerts use ``hst:{template_id}:{source_type}:{entity_uuid}``
    so the source_type lives at index 2.  For other formats, fall back
    to *alert_type* (threshold lookup will simply return False).
    """
    parts = alert.dedup_key.split(":")
    if len(parts) >= 3 and parts[0] == "hst":
        return parts[2]
    return alert.alert_type


async def process_feedback(
    alert_id: str,
    feedback: FeedbackType,
    storage: AlertStore,
    ensemble: DetectionEnsemble | None = None,
    pagerduty_routing_key: str = "",
    note: str = "",
) -> str:
    """Process feedback for an alert. Returns status message."""
    alert = await storage.get_alert_by_id(alert_id)
    if alert is None:
        raise ValueError(f"Alert {alert_id} not found")

    await storage.update_feedback(alert_id, feedback, note)

    msg = f"Alert {alert_id[:8]}... marked as {feedback.upper()}"

    if feedback == "fp" and ensemble is not None:
        source_key = _derive_source_key(alert)
        result = ensemble.adjust_upper_threshold(source_key, _FP_THRESHOLD_FACTOR)
        if result.status == "clamped":
            safe_key = source_key[:64]
            msg += (
                f". DSPOT threshold capped at {result.current_ratio:.2f}x baseline "
                f"for source {safe_key!r} — review detector for noise"
            )
        elif result.status == "applied":
            safe_key = source_key[:64]
            msg += f". DSPOT threshold adjusted for source {safe_key!r}"
        # not_calibrated: no CLI noise

    if feedback == "fp" and pagerduty_routing_key:
        dedup_key = f"{alert.alert_type}:{alert.rule_name}:{alert.entity_uuid}"
        await _resolve_pagerduty(dedup_key, pagerduty_routing_key)
        msg += ". PagerDuty incident resolved"

    return msg


async def _resolve_pagerduty(dedup_key: str, routing_key: str) -> None:
    """Open a one-shot aiohttp session and resolve the PD incident via shared helper."""
    import aiohttp

    from seerflow.alerting.sinks.pagerduty import post_resolve

    async with aiohttp.ClientSession() as session:
        await post_resolve(session, dedup_key, routing_key)
