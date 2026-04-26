"""GET /api/v1/health -- service health check (FastAPI version).

Returns 200 when all components are healthy, 503 when degraded.
Same contract as the legacy aiohttp health endpoint, including the
``detection`` (from ``DetectionEnsemble.get_health()``) and
``feedback`` (from ``await alert_store.get_feedback_stats()``)
extras when those dependencies are wired into the app (S-217).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response

from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_engines,
    get_health_state,
    get_storage,
)
from seerflow.api.schemas import HealthResponse

router = APIRouter(tags=["system"])

_HEALTHY_VALUES = frozenset({"running", "connected", "ok"})

HealthState = Annotated[dict[str, str], Depends(get_health_state)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]
Storage = Annotated[StorageDeps, Depends(get_storage)]


@router.get("/health", response_model=HealthResponse)
async def get_health(
    response: Response,
    health_state: HealthState,
    engines: Engines,
    storage: Storage,
) -> HealthResponse:
    """Return service health status."""
    all_healthy = all(v in _HEALTHY_VALUES for v in health_state.values())
    status: Literal["healthy", "degraded"] = "healthy" if all_healthy else "degraded"
    if not all_healthy:
        response.status_code = 503

    detection: dict[str, Any] | None = (
        engines.ensemble.get_health() if engines.ensemble is not None else None
    )
    feedback: dict[str, int] | None = None
    if storage.alert_store is not None:
        feedback = await storage.alert_store.get_feedback_stats()

    return HealthResponse(
        status=status,
        components=health_state,
        detection=detection,
        feedback=feedback,
    )
