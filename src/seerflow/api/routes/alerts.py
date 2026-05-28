"""Alert endpoints: list, detail, and feedback submission.

GET  /api/v1/alerts           -- paginated alert queries
GET  /api/v1/alerts/{id}      -- single alert detail
POST /api/v1/alerts/{id}/feedback -- TP/FP feedback
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from seerflow.api.deps import StorageDeps, get_storage, parse_timestamp_ns
from seerflow.api.limits import detail_limit, limiter, list_limit
from seerflow.api.schemas import (
    AlertResponse,
    ContributingEventResponse,
    FeedbackEventResponse,
    FeedbackRequest,
    PaginatedResponse,
)
from seerflow.models._types import AlertType
from seerflow.models.event import SEVERITY_MAX, SEVERITY_MIN
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.sigma.attack import is_valid_technique, resolve_tactic

if TYPE_CHECKING:
    import uuid

_log = logging.getLogger("seerflow")

router = APIRouter(tags=["alerts"])

Storage = Annotated[StorageDeps, Depends(get_storage)]

_VALID_ALERT_TYPES = frozenset(get_args(AlertType))

# S-338: lookback window opened around the alert when hydrating
# ``contributing_events`` for the detail endpoint. Mirrors the value used by
# ``seerflow.llm.explanation.service._EVENT_LOOKBACK_NS`` — wide enough to
# tolerate modest clock drift, narrow enough to keep the storage query cheap.
_DETAIL_EVENT_LOOKBACK_NS = 24 * 3600 * 1_000_000_000  # 24 hours
# Cap on hydrated rows. One screenful in the mockup grid is ~16 entries; we
# keep the JSON detail bounded for slow connections.
_DETAIL_CONTRIBUTING_EVENT_CAP = 16


async def _hydrate_contributing_events(
    storage: StorageDeps,
    alert_id: str,
    contributing: tuple[uuid.UUID, ...],
    entity_uuid: str,
    alert_ts_ns: int,
) -> list[ContributingEventResponse] | None:
    """Look up the events referenced by ``alert.contributing_events`` and
    convert them to ``ContributingEventResponse`` rows (S-338).

    Returns ``None`` when the alert references no events OR when the lookup
    window misses every referenced event (e.g. they aged out of hot
    storage). Either condition causes the route to omit the field from the
    response payload, which the dashboard tolerates.
    """
    if not contributing:
        return None
    wanted = set(contributing)
    time_range = TimeRange(
        start_ns=max(0, alert_ts_ns - _DETAIL_EVENT_LOOKBACK_NS),
        end_ns=alert_ts_ns + _DETAIL_EVENT_LOOKBACK_NS,
    )
    query = EventQuery(
        time_range=time_range,
        entity_uuid=entity_uuid,
        page=1,
        # Pull a generous slice so we can filter down to the referenced IDs.
        limit=min(1000, max(_DETAIL_CONTRIBUTING_EVENT_CAP * 8, 32)),
    )
    try:
        page = await storage.log_store.query_events(query)
    except Exception:  # pragma: no cover - defensive
        _log.warning(
            "alert detail: failed to hydrate contributing_events for %s",
            alert_id,
            exc_info=True,
        )
        return None
    picked = [ev for ev in page.items if ev.event_id in wanted]
    if not picked:
        return None
    # Oldest-first matches the explanation-service convention; cap to keep
    # the JSON payload bounded.
    picked.sort(key=lambda e: e.timestamp_ns)
    if len(picked) > _DETAIL_CONTRIBUTING_EVENT_CAP:
        picked = picked[-_DETAIL_CONTRIBUTING_EVENT_CAP:]
    return [ContributingEventResponse.from_event(ev) for ev in picked]


@router.get(
    "/alerts",
    response_model=PaginatedResponse[AlertResponse],
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def list_alerts(
    request: Request,
    storage: Storage,
    since: Annotated[str | None, Query(description="Start time (ISO-8601)")] = None,
    until: Annotated[str | None, Query(description="End time (ISO-8601)")] = None,
    alert_type: Annotated[str | None, Query(alias="type", description="Alert type")] = None,
    severity: Annotated[
        int | None,
        Query(
            ge=SEVERITY_MIN,
            le=SEVERITY_MAX,
            description=f"Minimum severity ({SEVERITY_MIN}-{SEVERITY_MAX})",
        ),
    ] = None,
    entity: Annotated[str | None, Query(description="Entity UUID")] = None,
    tactic: Annotated[str | None, Query(description="MITRE ATT&CK tactic", max_length=64)] = None,
    technique: Annotated[
        str | None, Query(description="MITRE ATT&CK technique", max_length=16)
    ] = None,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    limit: Annotated[int, Query(ge=1, description="Results per page")] = 50,
) -> PaginatedResponse[AlertResponse]:
    """Query alerts with filtering and pagination."""
    limit = min(limit, 1000)

    if alert_type is not None and alert_type not in _VALID_ALERT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid alert type: {alert_type!r}")

    resolved_tactic = tactic
    if tactic is not None:
        resolved_tactic = resolve_tactic(tactic)
        if resolved_tactic is None:
            raise HTTPException(status_code=422, detail=f"Unknown tactic: {tactic!r}")

    if technique is not None and not is_valid_technique(technique):
        raise HTTPException(status_code=422, detail=f"Invalid technique: {technique!r}")

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

    query = AlertQuery(
        time_range=time_range,
        alert_type=alert_type,  # type: ignore[arg-type]
        severity_min=severity,
        entity_uuid=entity,
        tactic=resolved_tactic,
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


@router.get(
    "/alerts/{alert_id}",
    response_model=AlertResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(detail_limit)
async def get_alert(
    request: Request,
    alert_id: Annotated[str, Path(max_length=64, description="Alert ID (UUID)")],
    storage: Storage,
) -> AlertResponse:
    """Get a single alert by ID.

    S-338: this endpoint hydrates ``contributing_events`` with per-event
    ``severity_text`` + ``entity_path`` so the dashboard's alert-detail grid
    can render the mockup's level / entity-path columns and row tinting
    without an extra round trip.
    """
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    hydrated = await _hydrate_contributing_events(
        storage,
        alert_id,
        alert.contributing_events,
        alert.entity_uuid,
        alert.timestamp_ns,
    )
    return AlertResponse.from_alert(alert, contributing_events=hydrated)


@router.post(
    "/alerts/{alert_id}/feedback",
    status_code=204,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(detail_limit)
async def submit_feedback(
    request: Request,
    alert_id: Annotated[str, Path(max_length=64, description="Alert ID (UUID)")],
    body: FeedbackRequest,
    storage: Storage,
) -> Response:
    """Submit TP/FP feedback for an alert."""
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if body.note:
        _log.info("Persisting feedback note (%d chars)", len(body.note))
    await storage.alert_store.update_feedback(
        alert_id, body.feedback, body.note or "", origin=body.origin
    )
    return Response(status_code=204)


@router.get(
    "/alerts/{alert_id}/feedback",
    response_model=PaginatedResponse[FeedbackEventResponse],
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(detail_limit)
async def list_feedback(
    request: Request,
    alert_id: Annotated[str, Path(max_length=64, description="Alert ID (UUID)")],
    storage: Storage,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    limit: Annotated[int, Query(ge=1, le=200, description="Results per page")] = 50,
) -> PaginatedResponse[FeedbackEventResponse]:
    """Return the feedback audit log for an alert, newest-first."""
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await storage.alert_store.list_feedback_events(alert_id, page=page, limit=limit)
    items = [FeedbackEventResponse.from_event(e) for e in result.items]
    return PaginatedResponse(
        items=items,
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_next=result.has_next,
    )
