"""TP/FP feedback processing — storage update + DSPOT threshold adjustment."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.models._types import FeedbackType
    from seerflow.storage.sqlite import SqliteBackend

_log = logging.getLogger("seerflow")

_FP_THRESHOLD_FACTOR = 1.05  # Multiplicative increase per FP


async def process_feedback(
    alert_id: str,
    feedback: FeedbackType,
    storage: SqliteBackend,
    ensemble: DetectionEnsemble | None = None,
    pagerduty_routing_key: str = "",
) -> str:
    """Process feedback for an alert. Returns status message."""
    alert = await storage.get_alert_by_id(alert_id)
    if alert is None:
        raise ValueError(f"Alert {alert_id} not found")

    await storage.update_feedback(alert_id, feedback)

    msg = f"Alert {alert_id[:8]}... marked as {feedback.upper()}"

    if feedback == "fp" and ensemble is not None:
        source_key = alert.alert_type  # Use alert_type as source key
        adjusted = ensemble.adjust_upper_threshold(source_key, _FP_THRESHOLD_FACTOR)
        if adjusted:
            msg += f". DSPOT threshold adjusted for source '{source_key}'"

    if feedback == "fp" and pagerduty_routing_key:
        dedup_key = f"{alert.alert_type}:{alert.rule_name}:{alert.entity_uuid}"
        await _resolve_pagerduty(dedup_key, pagerduty_routing_key)
        msg += ". PagerDuty incident resolved"

    return msg


async def _resolve_pagerduty(dedup_key: str, routing_key: str) -> None:
    """Send a PagerDuty resolve event via direct HTTP POST."""
    import aiohttp

    payload = {
        "routing_key": routing_key,
        "event_action": "resolve",
        "dedup_key": dedup_key,
    }
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp,
        ):
            if resp.status >= 400:
                _log.warning("PagerDuty resolve returned %d", resp.status)
    except Exception as exc:
        _log.warning("PagerDuty resolve failed: %s", exc)
