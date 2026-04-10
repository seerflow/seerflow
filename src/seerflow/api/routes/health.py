"""GET /api/v1/health -- service health check (FastAPI version).

Returns 200 when all components are healthy, 503 when degraded.
Same contract as the existing aiohttp health endpoint.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response

from seerflow.api.deps import get_health_state
from seerflow.api.schemas import HealthResponse

router = APIRouter(tags=["system"])

_HEALTHY_VALUES = frozenset({"running", "connected", "ok"})

HealthState = Annotated[dict[str, str], Depends(get_health_state)]


@router.get("/health", response_model=HealthResponse)
async def get_health(
    response: Response,
    health_state: HealthState,
) -> HealthResponse:
    """Return service health status."""
    all_healthy = all(v in _HEALTHY_VALUES for v in health_state.values())
    status: Literal["healthy", "degraded"] = "healthy" if all_healthy else "degraded"
    if not all_healthy:
        response.status_code = 503
    return HealthResponse(status=status, components=health_state)
