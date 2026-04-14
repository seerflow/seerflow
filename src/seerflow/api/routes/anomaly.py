"""GET /api/v1/anomaly/timeline -- bucketed anomaly-score series for the dashboard.

Joins the in-memory AnomalyTimelineRing with the persistent AlertStore to
produce {bucket_start_ns, max_score, avg_score, event_count, upper_threshold,
alert_count} tuples. Meta echoes the resolved (range, resolution, source).
"""

from __future__ import annotations

import re
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from seerflow.api.anomaly_timeline import (
    RANGE_NS,
    RESOLUTION_NS,
    AnomalyTimelineRing,
    allowed_resolutions,
    default_resolution,
)
from seerflow.api.deps import StorageDeps, get_anomaly_timeline_ring, get_storage
from seerflow.api.limits import limiter, list_limit
from seerflow.models.query import AlertQuery, TimeRange

router = APIRouter(tags=["anomaly"])

_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


RangeArg = Annotated[Literal["1h", "6h", "24h", "7d"], Query(description="Window size")]
ResolutionArg = Annotated[
    Literal["1m", "5m", "15m", "1h"] | None,
    Query(description="Bucket size (defaults to the smallest allowed for range)"),
]
SourceArg = Annotated[str | None, Query(description="Source type filter", max_length=64)]


@router.get(
    "/anomaly/timeline",
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def get_anomaly_timeline(
    request: Request,
    storage: Annotated[StorageDeps, Depends(get_storage)],
    ring: Annotated[AnomalyTimelineRing, Depends(get_anomaly_timeline_ring)],
    range: RangeArg = "1h",  # noqa: A002 -- matches public query param name
    resolution: ResolutionArg = None,
    source: SourceArg = None,
) -> dict[str, Any]:
    """Return a bucketed anomaly-score series for the requested window."""
    if source is not None and not _SOURCE_RE.match(source):
        raise HTTPException(status_code=422, detail="source contains invalid characters")

    resolved_resolution = resolution or default_resolution(range)
    if resolved_resolution not in allowed_resolutions(range):
        raise HTTPException(
            status_code=422,
            detail=f"resolution {resolved_resolution!r} not allowed for range {range!r}",
        )

    now_ns = time.time_ns()
    items = ring.query(
        range_ns=RANGE_NS[range],
        resolution_ns=RESOLUTION_NS[resolved_resolution],
        source=source,
        now_ns=now_ns,
    )

    start_ns = items[0].bucket_start_ns if items else now_ns - RANGE_NS[range]
    end_ns = now_ns
    alert_page = await storage.alert_store.query_alerts(
        AlertQuery(time_range=TimeRange(start_ns=start_ns, end_ns=end_ns), limit=10_000)
    )
    bucket_ns = RESOLUTION_NS[resolved_resolution]
    alert_counts: dict[int, int] = {}
    for a in alert_page.items:
        key = (a.timestamp_ns // bucket_ns) * bucket_ns
        alert_counts[key] = alert_counts.get(key, 0) + 1

    out = [
        {
            "bucket_start_ns": b.bucket_start_ns,
            "max_score": b.max_score,
            "avg_score": b.avg_score,
            "event_count": b.event_count,
            "upper_threshold": b.upper_threshold,
            "alert_count": alert_counts.get(b.bucket_start_ns, 0),
        }
        for b in items
    ]

    return {
        "meta": {"range": range, "resolution": resolved_resolution, "source": source},
        "items": out,
    }
