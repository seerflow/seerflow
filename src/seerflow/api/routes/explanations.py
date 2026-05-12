"""Alert explanation endpoints (S-071, FR-056).

Two routes mounted under ``/api/v1/alerts/{alert_id}/``:

- ``POST /explain``        — generate (or hit cache) and return the explanation.
- ``GET  /explanation``    — return the cached explanation only (never generates).

Both routes return HTTP 503 when the LLM backend is not ``ready``
(``app.state.explanation_service is None``) so the dashboard can grey
out the "Explain" button. ``GET`` additionally returns 404 with
``{"detail": "no_cached_explanation"}`` when no cached entry exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from seerflow.api.deps import (
    StorageDeps,
    get_explanation_service,
    get_health_state,
    get_storage,
)
from seerflow.api.limits import detail_limit, limiter
from seerflow.api.schemas import AlertExplanationResponse

if TYPE_CHECKING:
    from seerflow.llm.explanation.service import AlertExplanationService

_log = logging.getLogger("seerflow")

router = APIRouter(tags=["alerts"])

_Storage = Annotated[StorageDeps, Depends(get_storage)]
_HealthState = Annotated[dict[str, str], Depends(get_health_state)]
_Service = Annotated["AlertExplanationService | None", Depends(get_explanation_service)]


def _llm_not_ready_response(health_state: dict[str, str]) -> HTTPException:
    """Build a 503 with ``status`` reflecting the health surface."""
    status = health_state.get("llm", "disabled")
    return HTTPException(
        status_code=503,
        detail={"detail": "llm_not_ready", "status": status},
    )


@router.post(
    "/alerts/{alert_id}/explain",
    response_model=AlertExplanationResponse,
    responses={
        404: {"description": "Alert not found"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "LLM backend failed"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(detail_limit)
async def explain_alert(
    request: Request,
    alert_id: Annotated[str, Path(max_length=64, description="Alert ID (UUID)")],
    service: _Service,
    health_state: _HealthState,
    storage: _Storage,
) -> AlertExplanationResponse:
    """Generate (or return cached) explanation for ``alert_id``."""
    if service is None:
        raise _llm_not_ready_response(health_state)

    # Ensure the alert exists before invoking the LLM. This double-checks
    # so we can distinguish 404 (unknown alert) from 502 (LLM failure).
    alert = await storage.alert_store.get_alert_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    try:
        result = await service.explain(alert_id)
    except Exception:
        _log.error("explanation: backend raised for alert_id=%s", alert_id, exc_info=True)
        raise HTTPException(status_code=502, detail="llm_failed") from None

    if result is None:
        # The service double-checks the alert; this is the race-window
        # safety net (alert deleted between the route's check and the
        # service's check). Same outcome as a fresh 404.
        raise HTTPException(status_code=404, detail="Alert not found")

    return AlertExplanationResponse.from_result(result)


@router.get(
    "/alerts/{alert_id}/explanation",
    response_model=AlertExplanationResponse,
    responses={
        404: {"description": "No cached explanation"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(detail_limit)
async def get_cached_explanation(
    request: Request,
    alert_id: Annotated[str, Path(max_length=64, description="Alert ID (UUID)")],
    service: _Service,
    health_state: _HealthState,
) -> AlertExplanationResponse:
    """Return the cached explanation (never triggers generation)."""
    if service is None:
        raise _llm_not_ready_response(health_state)

    cached = await service.cache.get(alert_id)
    if cached is None:
        raise HTTPException(status_code=404, detail="no_cached_explanation")
    return AlertExplanationResponse.from_result(cached)
