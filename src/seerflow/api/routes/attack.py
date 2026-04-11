"""ATT&CK coverage matrix endpoint.

GET /api/v1/attack/coverage -- coverage matrix (tactics x techniques x counts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from seerflow.api.attack import (
    build_matrix,
    collect_alert_cells,
    collect_correlation_cells,
    collect_sigma_cells,
)
from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_engines,
    get_storage,
    parse_timestamp_ns,
)
from seerflow.api.schemas import AttackCoverageResponse
from seerflow.models.query import AlertQuery, TimeRange

router = APIRouter(tags=["attack"])

Storage = Annotated[StorageDeps, Depends(get_storage)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]

_DEFAULT_WINDOW_DAYS = 30
_MAX_ALERT_SCAN = 10_000


def _parse_iso_or_422(value: str) -> datetime:
    try:
        ns = parse_timestamp_ns(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid ISO-8601 timestamp"
        ) from exc
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC)


@router.get("/attack/coverage", response_model=AttackCoverageResponse)
async def get_coverage(
    storage: Storage,
    engines: Engines,
    since: Annotated[
        str | None, Query(description="Start time (ISO-8601)")
    ] = None,
    until: Annotated[
        str | None, Query(description="End time (ISO-8601)")
    ] = None,
) -> AttackCoverageResponse:
    """Return the ATT&CK coverage matrix.

    The default window is the last ``_DEFAULT_WINDOW_DAYS`` days. Unlike
    ``/api/v1/alerts`` which treats missing ``since``/``until`` as an
    unbounded query, this endpoint always applies a bounded window to
    keep dashboard queries predictable.
    """
    window_until = (
        datetime.now(UTC) if until is None else _parse_iso_or_422(until)
    )
    window_since = (
        window_until - timedelta(days=_DEFAULT_WINDOW_DAYS)
        if since is None
        else _parse_iso_or_422(since)
    )

    if window_since > window_until:
        raise HTTPException(
            status_code=400, detail="since must be before until"
        )

    time_range = TimeRange(
        start_ns=int(window_since.timestamp() * 1_000_000_000),
        end_ns=int(window_until.timestamp() * 1_000_000_000),
    )
    alert_page = await storage.alert_store.query_alerts(
        AlertQuery(time_range=time_range, page=1, limit=_MAX_ALERT_SCAN)
    )

    rule_counts: dict[tuple[str, str], int] = dict(
        collect_sigma_cells(engines.sigma_engine)
    )
    for key, count in collect_correlation_cells(engines.correlation_rules).items():
        rule_counts[key] = rule_counts.get(key, 0) + count

    alert_counts = collect_alert_cells(alert_page.items)

    return build_matrix(
        rule_counts,
        alert_counts,
        window_since=window_since,
        window_until=window_until,
    )
