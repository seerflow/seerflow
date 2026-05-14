"""GET /api/v1/stats -- pipeline statistics.

Combines persistent storage counts (events, alerts, severity breakdown,
feedback) with live pipeline metrics (uptime, throughput, active sources,
model count) when a metrics provider is wired.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Annotated, Any

import msgspec
from fastapi import APIRouter, Depends, Request

from seerflow.api.deps import (
    StorageDeps,
    get_pipeline_metrics_provider,
    get_storage,
)
from seerflow.api.limits import limiter, list_limit
from seerflow.api.metrics import MetricsProvider, compute_uptime_rate
from seerflow.api.schemas import StatsResponse
from seerflow.models.query import AlertQuery, EventQuery
from seerflow.utils.log_sanitize import sanitize_exception

_log = logging.getLogger("seerflow.api.stats")

router = APIRouter(tags=["system"])

Storage = Annotated[StorageDeps, Depends(get_storage)]
MetricsProviderDep = Annotated[MetricsProvider | None, Depends(get_pipeline_metrics_provider)]


@router.get(
    "/stats",
    response_model=StatsResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def get_stats(
    request: Request,
    storage: Storage,
    metrics_provider: MetricsProviderDep,
) -> StatsResponse:
    """Return pipeline statistics (persistent counts + live metrics)."""
    event_page = await storage.log_store.query_events(EventQuery(limit=1))
    alert_page = await storage.alert_store.query_alerts(AlertQuery(limit=1))
    feedback_stats = await storage.alert_store.get_feedback_stats()

    try:
        alerts_by_severity = await storage.alert_store.count_by_severity()
    except Exception as exc:
        # Any storage error should degrade to {} rather than 500 the endpoint.
        # ``exc_info=True`` is avoided here: ``asyncpg`` exceptions can embed
        # the DSN (including password) in the traceback chain, so the
        # sanitized single-line summary is logged instead (S-080, S-056 review).
        _log.warning(
            "count_by_severity failed; returning empty breakdown: %s",
            sanitize_exception(exc),
        )
        alerts_by_severity = {}

    uptime_seconds = 0.0
    event_rate_per_sec = 0.0
    total_events_processed = 0
    active_sources = 0
    model_count = 0
    taxii_payload: dict[str, dict[str, Any]] | None = None
    ioc_matcher_payload: dict[str, object] | None = None
    ioc_enrichment_payload: dict[str, object] | None = None

    if metrics_provider is not None:
        try:
            snapshot = metrics_provider()
            uptime_seconds, event_rate_per_sec = compute_uptime_rate(
                snapshot.started_monotonic,
                snapshot.total_events_processed,
            )
            total_events_processed = snapshot.total_events_processed
            active_sources = snapshot.active_sources
            model_count = snapshot.model_count
            if snapshot.taxii is not None and snapshot.taxii.feeds:
                taxii_payload = {
                    feed_id: dataclasses.asdict(feed_metrics)
                    for feed_id, feed_metrics in snapshot.taxii.feeds.items()
                }
            if snapshot.ioc_matcher is not None:
                ioc_matcher_payload = msgspec.to_builtins(snapshot.ioc_matcher)
            if snapshot.ioc_enrichment is not None:
                ioc_enrichment_payload = msgspec.to_builtins(snapshot.ioc_enrichment)
        except Exception as exc:
            # Provider failure must not 500 the endpoint; degrade to zero fields.
            # ``exc_info=True`` skipped — DSN-bearing exceptions sanitized
            # via ``sanitize_exception`` instead (S-080, S-056 review).
            _log.warning(
                "pipeline metrics provider failed: %s",
                sanitize_exception(exc),
            )

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
        taxii=taxii_payload,
        ioc_matcher=ioc_matcher_payload,
        ioc_enrichment=ioc_enrichment_payload,
    )
