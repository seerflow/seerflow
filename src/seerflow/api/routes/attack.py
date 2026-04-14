"""ATT&CK coverage matrix endpoint.

GET /api/v1/attack/coverage -- coverage matrix (tactics x techniques x counts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from seerflow.api.attack import (
    build_matrix,
    collect_alert_cells,
    collect_correlation_cells,
    collect_sigma_cells,
    merge_rule_counts,
)
from seerflow.api.constants import MAX_ALERT_SCAN
from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_engines,
    get_storage,
    parse_timestamp_ns,
)
from seerflow.api.limits import coverage_limit, limiter
from seerflow.api.schemas import AttackCoverageResponse
from seerflow.models.query import AlertQuery, TimeRange

if TYPE_CHECKING:
    from seerflow.models.alert import Alert
    from seerflow.storage.protocols import AlertStore

router = APIRouter(tags=["attack"])

Storage = Annotated[StorageDeps, Depends(get_storage)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]

_DEFAULT_WINDOW_DAYS = 30


def _parse_iso_or_422(value: str) -> datetime:
    try:
        ns = parse_timestamp_ns(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid ISO-8601 timestamp") from exc
    return datetime.fromtimestamp(ns / 1_000_000_000, tz=UTC)


def _resolve_window(since: str | None, until: str | None) -> tuple[datetime, datetime]:
    window_until = datetime.now(UTC) if until is None else _parse_iso_or_422(until)
    window_since = (
        window_until - timedelta(days=_DEFAULT_WINDOW_DAYS)
        if since is None
        else _parse_iso_or_422(since)
    )
    if window_since > window_until:
        raise HTTPException(status_code=400, detail="since must be before until")
    return window_since, window_until


async def _scan_alerts(
    alert_store: AlertStore,
    time_range: TimeRange,
) -> list[Alert]:
    """Fetch up to ``MAX_ALERT_SCAN`` alerts in a single SQL query."""
    page = await alert_store.query_alerts(
        AlertQuery(time_range=time_range, page=1, limit=MAX_ALERT_SCAN)
    )
    return list(page.items)


@router.get(
    "/attack/coverage",
    response_model=AttackCoverageResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(coverage_limit)
async def get_coverage(
    request: Request,
    storage: Storage,
    engines: Engines,
    since: Annotated[str | None, Query(description="Start time (ISO-8601)", max_length=64)] = None,
    until: Annotated[str | None, Query(description="End time (ISO-8601)", max_length=64)] = None,
) -> AttackCoverageResponse:
    """Return the ATT&CK coverage matrix.

    The default window is the last ``_DEFAULT_WINDOW_DAYS`` days. Unlike
    ``/api/v1/alerts`` which treats missing ``since``/``until`` as an
    unbounded query, this endpoint always applies a bounded window to
    keep dashboard queries predictable.
    """
    window_since, window_until = _resolve_window(since, until)
    time_range = TimeRange(
        start_ns=int(window_since.timestamp() * 1_000_000_000),
        end_ns=int(window_until.timestamp() * 1_000_000_000),
    )
    alerts = await _scan_alerts(storage.alert_store, time_range)
    rule_counts = merge_rule_counts(
        collect_sigma_cells(engines.sigma_engine),
        collect_correlation_cells(engines.correlation_rules),
    )
    return build_matrix(
        rule_counts,
        collect_alert_cells(alerts),
        window_since=window_since,
        window_until=window_until,
    )
