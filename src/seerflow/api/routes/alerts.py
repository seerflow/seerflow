"""Alert endpoints: list, detail, and feedback submission.

GET  /api/v1/alerts           -- paginated alert queries
GET  /api/v1/alerts/{id}      -- single alert detail
POST /api/v1/alerts/{id}/feedback -- TP/FP feedback
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from seerflow.api.deps import StorageDeps, get_storage, parse_timestamp_ns
from seerflow.api.schemas import AlertResponse, FeedbackRequest, PaginatedResponse
from seerflow.models.query import AlertQuery, TimeRange

if TYPE_CHECKING:
    from seerflow.models._types import AlertType

router = APIRouter(tags=["alerts"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


@router.get("/alerts", response_model=PaginatedResponse[AlertResponse])
async def list_alerts(
    storage: Storage,
    since: str | None = Query(None, description="Start time (ISO-8601)"),
    until: str | None = Query(None, description="End time (ISO-8601)"),
    alert_type: str | None = Query(None, alias="type", description="Alert type"),
    severity: int | None = Query(None, description="Minimum severity (0-6)"),
    entity: str | None = Query(None, description="Entity UUID"),
    tactic: str | None = Query(None, description="MITRE ATT&CK tactic"),
    technique: str | None = Query(None, description="MITRE ATT&CK technique"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, description="Results per page"),
) -> PaginatedResponse[AlertResponse]:
    """Query alerts with filtering and pagination."""
    limit = min(limit, 1000)

    time_range: TimeRange | None = None
    if since is not None or until is not None:
        try:
            start_ns = parse_timestamp_ns(since) if since else 0
            end_ns = parse_timestamp_ns(until) if until else 2**63 - 1
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid ISO-8601 timestamp: {exc}"
            ) from exc
        if start_ns > end_ns:
            raise HTTPException(status_code=400, detail="since must be before until")
        time_range = TimeRange(start_ns=start_ns, end_ns=end_ns)

    typed_alert: AlertType | None = cast("AlertType | None", alert_type)
    query = AlertQuery(
        time_range=time_range,
        alert_type=typed_alert,
        severity_min=severity,
        entity_uuid=entity,
        tactic=tactic,
        technique=technique,
        page=page,
        limit=limit,
    )
    result = await storage.alert_store.query_alerts(query)
    items = [AlertResponse.from_alert(a) for a in result.items]
    return PaginatedResponse(
        items=items,
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_next=result.has_next,
    )


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    storage: Storage,
) -> AlertResponse:
    """Get a single alert by ID."""
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertResponse.from_alert(alert)


@router.post("/alerts/{alert_id}/feedback", status_code=204)
async def submit_feedback(
    alert_id: str,
    body: FeedbackRequest,
    storage: Storage,
) -> Response:
    """Submit TP/FP feedback for an alert."""
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    await storage.alert_store.update_feedback(alert_id, body.feedback)
    return Response(status_code=204)
