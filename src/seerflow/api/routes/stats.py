"""GET /api/v1/stats -- pipeline statistics.

Combines persistent storage counts (events, alerts, severity breakdown,
feedback) with live pipeline metrics (uptime, throughput, active sources,
model count) when a metrics provider is wired.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends

from seerflow.api.deps import (
    StorageDeps,
    get_pipeline_metrics_provider,
    get_storage,
)
from seerflow.api.metrics import MetricsProvider
from seerflow.api.schemas import StatsResponse
from seerflow.models.query import AlertQuery, EventQuery

_log = logging.getLogger("seerflow.api.stats")

router = APIRouter(tags=["system"])

Storage = Annotated[StorageDeps, Depends(get_storage)]
MetricsProviderDep = Annotated[MetricsProvider | None, Depends(get_pipeline_metrics_provider)]


def _compute_rate(started_monotonic: float, events: int) -> tuple[float, float]:
    """Return ``(uptime_seconds, event_rate_per_sec)``.

    Rate is clamped to ``0.0`` when uptime is ``< 1s`` to avoid divide-by-zero
    and first-second spikes.
    """
    uptime = max(0.0, time.monotonic() - started_monotonic)
    if uptime < 1.0:
        return uptime, 0.0
    return uptime, events / uptime


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    storage: Storage,
    metrics_provider: MetricsProviderDep,
) -> StatsResponse:
    """Return pipeline statistics (persistent counts + live metrics)."""
    event_page = await storage.log_store.query_events(EventQuery(limit=1))
    alert_page = await storage.alert_store.query_alerts(AlertQuery(limit=1))
    feedback_stats = await storage.alert_store.get_feedback_stats()

    try:
        alerts_by_severity = await storage.alert_store.count_by_severity()
    except Exception:
        # Any storage error should degrade to {} rather than 500 the endpoint.
        _log.warning("count_by_severity failed; returning empty breakdown", exc_info=True)
        alerts_by_severity = {}

    uptime_seconds = 0.0
    event_rate_per_sec = 0.0
    total_events_processed = 0
    active_sources = 0
    model_count = 0

    if metrics_provider is not None:
        try:
            snapshot = metrics_provider()
            uptime_seconds, event_rate_per_sec = _compute_rate(
                snapshot.started_monotonic,
                snapshot.total_events_processed,
            )
            total_events_processed = snapshot.total_events_processed
            active_sources = snapshot.active_sources
            model_count = snapshot.model_count
        except Exception:
            # Provider failure must not 500 the endpoint; degrade to zero fields.
            _log.warning("pipeline metrics provider failed", exc_info=True)

    return StatsResponse(
        total_events=event_page.total,
        total_alerts=alert_page.total,
        alerts_by_severity=alerts_by_severity,
        feedback_stats=feedback_stats,
        uptime_seconds=uptime_seconds,
        event_rate_per_sec=event_rate_per_sec,
        total_events_processed=total_events_processed,
        active_sources=active_sources,
        model_count=model_count,
    )
