"""ATT&CK coverage matrix endpoint.

GET /api/v1/attack/coverage -- coverage matrix (tactics x techniques x counts).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

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

if TYPE_CHECKING:
    from seerflow.models.alert import Alert

_log = logging.getLogger(__name__)

router = APIRouter(tags=["attack"])

Storage = Annotated[StorageDeps, Depends(get_storage)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]

_DEFAULT_WINDOW_DAYS = 30
# Maximum number of alerts scanned for coverage in one request. AlertQuery
# caps ``limit`` at 1000, so we page through ``_MAX_SCAN_PAGES`` pages of
# 1000 alerts each. 10 pages * 1000 = 10k alerts.
_MAX_SCAN_PAGES = 10
_SCAN_PAGE_SIZE = 1_000
_MAX_ALERT_SCAN = _MAX_SCAN_PAGES * _SCAN_PAGE_SIZE


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
    alert_store: object,
    time_range: TimeRange,
) -> list[Alert]:
    """Page through up to ``_MAX_ALERT_SCAN`` alerts and warn if the cap hits."""
    alerts: list[Alert] = []
    page = None
    for page_num in range(1, _MAX_SCAN_PAGES + 1):
        page = await alert_store.query_alerts(  # type: ignore[attr-defined]
            AlertQuery(time_range=time_range, page=page_num, limit=_SCAN_PAGE_SIZE)
        )
        alerts.extend(page.items)
        if not page.has_next:
            break
    if page is not None and page.has_next:
        _log.warning(
            "attack/coverage alert scan hit cap (%d alerts); "
            "summary counts may understate the true window total",
            _MAX_ALERT_SCAN,
        )
    return alerts


@router.get("/attack/coverage", response_model=AttackCoverageResponse)
async def get_coverage(
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

    rule_counts: dict[tuple[str, str], int] = dict(collect_sigma_cells(engines.sigma_engine))
    for key, count in collect_correlation_cells(engines.correlation_rules).items():
        rule_counts[key] = rule_counts.get(key, 0) + count

    return build_matrix(
        rule_counts,
        collect_alert_cells(alerts),
        window_since=window_since,
        window_until=window_until,
    )
