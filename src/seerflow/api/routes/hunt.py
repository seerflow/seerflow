"""Natural language threat hunting endpoint (S-072, FR-057).

``POST /api/v1/hunt`` accepts ``{"query": "..."}``, translates via the
configured LLM backend, executes the resulting ``EventQuery`` against the
``LogStore``, and returns the matching events plus the translated filters
for transparency.

Returns HTTP 503 when the LLM backend is not ``ready`` (``app.state.hunt_service
is None``) so the dashboard / CLI can present a graceful fallback message.
Returns HTTP 502 when the LLM call itself fails (timeout, runtime error)
— same contract as ``/explain``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from seerflow.api.deps import get_health_state, get_hunt_service
from seerflow.api.limits import detail_limit, limiter
from seerflow.api.schemas import NLHuntRequest, NLHuntResponse

if TYPE_CHECKING:
    from seerflow.llm.hunt.service import NaturalLanguageHuntService

_log = logging.getLogger("seerflow")

router = APIRouter(tags=["hunt"])

_HealthState = Annotated[dict[str, str], Depends(get_health_state)]
_Service = Annotated["NaturalLanguageHuntService | None", Depends(get_hunt_service)]


def _llm_not_ready_response(health_state: dict[str, str]) -> HTTPException:
    """Build a 503 with ``status`` reflecting the health surface."""
    status = health_state.get("llm", "disabled")
    return HTTPException(
        status_code=503,
        detail={"detail": "llm_not_ready", "status": status},
    )


@router.post(
    "/hunt",
    response_model=NLHuntResponse,
    responses={
        400: {"description": "Invalid query"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "LLM backend failed"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(detail_limit)
async def hunt(
    request: Request,
    payload: NLHuntRequest,
    service: _Service,
    health_state: _HealthState,
) -> NLHuntResponse:
    """Translate ``payload.query`` and return matching events."""
    if service is None:
        raise _llm_not_ready_response(health_state)

    try:
        result = await service.hunt(payload.query)
    except ValueError as exc:
        # Empty query or over-budget query — return 400.
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TimeoutError:
        _log.warning("hunt: backend timeout", exc_info=True)
        raise HTTPException(status_code=502, detail="llm_failed") from None
    except Exception:
        _log.error("hunt: backend raised", exc_info=True)
        raise HTTPException(status_code=502, detail="llm_failed") from None

    return NLHuntResponse.from_result(result)
