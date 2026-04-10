"""GET /api/v1/stats -- basic pipeline statistics.

Returns total alert count and feedback breakdown. Intentionally
lightweight -- S-056 adds throughput/latency/config details.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from seerflow.api.deps import StorageDeps, get_storage
from seerflow.api.schemas import StatsResponse
from seerflow.models.query import AlertQuery, EventQuery

router = APIRouter(tags=["system"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    storage: Storage,
) -> StatsResponse:
    """Return basic pipeline statistics.

    Uses query_events/query_alerts with limit=1 to retrieve totals since
    the storage Protocol has no dedicated count methods yet (S-056).
    alerts_by_severity is stubbed until AlertStore gains count_by_severity.
    """
    event_page = await storage.log_store.query_events(EventQuery(limit=1))
    alert_page = await storage.alert_store.query_alerts(AlertQuery(limit=1))
    feedback_stats = await storage.alert_store.get_feedback_stats()
    return StatsResponse(
        total_events=event_page.total,
        total_alerts=alert_page.total,
        alerts_by_severity={},  # S-056: needs AlertStore.count_by_severity
        feedback_stats=feedback_stats,
    )
