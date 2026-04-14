"""GET /api/v1/events -- paginated event queries.

Converts query params to EventQuery, delegates to LogStore.query_events,
and returns PaginatedResponse[EventResponse].
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from seerflow.api.deps import StorageDeps, get_storage, parse_timestamp_ns
from seerflow.api.limits import limiter, list_limit
from seerflow.api.schemas import EventResponse, PaginatedResponse
from seerflow.models.query import EventQuery, TimeRange

router = APIRouter(tags=["events"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


@router.get("/events", response_model=PaginatedResponse[EventResponse])
@limiter.limit(list_limit)
async def list_events(
    request: Request,
    storage: Storage,
    since: Annotated[str | None, Query(description="Start time (ISO-8601)")] = None,
    until: Annotated[str | None, Query(description="End time (ISO-8601)")] = None,
    source: Annotated[str | None, Query(description="Source type filter")] = None,
    severity: Annotated[
        int | None, Query(ge=0, le=6, description="Minimum severity (0-6)")
    ] = None,
    template_id: Annotated[int | None, Query(description="Drain3 template ID")] = None,
    entity: Annotated[str | None, Query(description="Entity UUID")] = None,
    q: Annotated[str | None, Query(description="Full-text search query", max_length=256)] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    limit: Annotated[int, Query(ge=1, description="Results per page")] = 50,
) -> PaginatedResponse[EventResponse]:
    """Query events with filtering and pagination."""
    limit = min(limit, 1000)

    time_range: TimeRange | None = None
    if since is not None or until is not None:
        try:
            start_ns = parse_timestamp_ns(since) if since else 0
            end_ns = parse_timestamp_ns(until) if until else 2**63 - 1
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid ISO-8601 timestamp") from exc
        if start_ns > end_ns:
            raise HTTPException(status_code=400, detail="since must be before until")
        time_range = TimeRange(start_ns=start_ns, end_ns=end_ns)

    query = EventQuery(
        time_range=time_range,
        source_type=source,
        severity_min=severity,
        template_id=template_id,
        entity_uuid=entity,
        text_query=q,
        page=page,
        limit=limit,
    )
    result = await storage.log_store.query_events(query)
    items = [EventResponse.from_event(e) for e in result.items]
    return PaginatedResponse(
        items=items,
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_next=result.has_next,
    )
