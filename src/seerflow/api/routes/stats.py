"""GET /api/v1/stats -- basic pipeline statistics.

Returns total alert count and feedback breakdown. Intentionally
lightweight -- S-056 adds throughput/latency/config details.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from seerflow.api.deps import StorageDeps, get_storage
from seerflow.api.schemas import StatsResponse
from seerflow.models.query import AlertQuery

router = APIRouter(tags=["system"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    storage: Storage,
) -> StatsResponse:
    """Return basic pipeline statistics."""
    alert_page = await storage.alert_store.query_alerts(AlertQuery(limit=1))
    feedback_stats = await storage.alert_store.get_feedback_stats()
    return StatsResponse(
        total_alerts=alert_page.total,
        alerts_by_severity={},
        feedback_stats=feedback_stats,
    )
