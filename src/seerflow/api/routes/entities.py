"""GET /api/v1/entities/search -- entity search endpoint.

Falls back to LogStore.search_text when no EntityStore is configured,
extracting entity references from matching events. Each result is stamped
with a deterministic UUID5 derived via the existing generate_*_id helpers.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid as _uuid_mod
from collections.abc import Sequence  # noqa: TC003 — runtime use in _bucket_alerts signature
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Final, Literal

import msgspec
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from seerflow.api.anomaly_timeline import (
    RANGE_NS,
    RESOLUTION_NS,
    allowed_resolutions,
    default_resolution,
)
from seerflow.api.deps import (
    StorageDeps,
    get_storage,
    require_entity_store,
)
from seerflow.api.limits import detail_limit, limiter, list_limit
from seerflow.api.schemas import (
    EntityRelationResponse,
    EntitySearchResult,
    EntityTimelineResponse,
    EventResponse,
    RiskBucketResponse,
    RiskHistoryMetaResponse,
    RiskHistoryResponse,
)
from seerflow.models.alert import Alert  # noqa: TC001 — runtime use in _bucket_alerts signature
from seerflow.models.entity import (
    generate_domain_id,
    generate_host_id,
    generate_ip_id,
    generate_user_id,
    normalize_username,
)
from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.storage.protocols import EntityStore  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.models.event import SeerflowEvent

_log = logging.getLogger(__name__)

router = APIRouter(tags=["entities"])

Storage = Annotated[StorageDeps, Depends(get_storage)]


def _uuid_for_ip(value: str) -> str:
    return str(generate_ip_id(value))


def _uuid_for_user(value: str) -> str:
    username, domain = normalize_username(value)
    return str(generate_user_id(username, domain))


def _uuid_for_host(value: str) -> str:
    return str(generate_host_id(value))


def _uuid_for_domain(value: str) -> str:
    return str(generate_domain_id(value))


DEFAULT_TIMELINE_WINDOW_NS = 24 * 60 * 60 * 1_000_000_000  # 24h
_MAX_TIMESTAMP_NS = 2**63 - 1  # SQLite int64 ceiling (~year 2262)

_ALERT_QUERY_LIMIT: Final[int] = 10_000  # S-060.F1: per-request alert scan ceiling.


def _bucket_alerts(
    alerts: Sequence[Alert],
    *,
    now_ns: int,
    range_ns: int,
    res_ns: int,
) -> list[RiskBucketResponse]:
    """Bucket ``alerts`` into zero-filled RiskBucket entries over ``[now-range, now)``.

    Buckets are half-open ``[bucket_start_ns, bucket_start_ns + res_ns)``.
    An alert with ``timestamp_ns % res_ns == 0`` lands in the *later* bucket.
    Empty buckets appear with ``points=0.0``, ``alert_count=0``, ``top_rule_name=""``.
    ``top_rule_name`` is the rule name of the max-``risk_score`` alert in the
    bucket; ties break by earliest ``timestamp_ns``.
    """
    start_ns = now_ns - range_ns
    first_bucket = (start_ns // res_ns) * res_ns
    bucket_count = math.ceil((now_ns - first_bucket) / res_ns)

    @dataclass(slots=True)
    class _Acc:
        points: float = 0.0
        alert_count: int = 0
        max_score: float = -1.0
        max_ts_ns: int = 0
        top_rule_name: str = ""

    buckets: dict[int, _Acc] = {}
    for a in alerts:
        key = (a.timestamp_ns // res_ns) * res_ns
        acc = buckets.setdefault(key, _Acc())
        acc.points += a.risk_score
        acc.alert_count += 1
        if (
            acc.max_score < 0
            or a.risk_score > acc.max_score
            or (a.risk_score == acc.max_score and a.timestamp_ns < acc.max_ts_ns)
        ):
            acc.max_score = a.risk_score
            acc.max_ts_ns = a.timestamp_ns
            acc.top_rule_name = a.rule_name or ""

    items: list[RiskBucketResponse] = []
    for i in range(bucket_count):
        b = first_bucket + i * res_ns
        got = buckets.get(b)
        items.append(
            RiskBucketResponse(
                bucket_start_ns=b,
                points=got.points if got else 0.0,
                alert_count=got.alert_count if got else 0,
                top_rule_name=got.top_rule_name if got else "",
            )
        )
    return items


def _coerce_time_range(start_ns: int | None, end_ns: int | None) -> TimeRange:
    """Default to last 24 hours if either bound is omitted.

    If only ``end_ns`` is supplied and smaller than the 24h window, the
    computed ``start_ns`` is clamped to 0 rather than going negative.
    """
    now = time.time_ns()
    end = end_ns if end_ns is not None else now
    start = start_ns if start_ns is not None else max(0, end - DEFAULT_TIMELINE_WINDOW_NS)
    return TimeRange(start_ns=start, end_ns=end)


# Only the FR-036 pivot types carry UUIDs. Files/processes/hashes are shown in
# the timeline but are not search pivot targets.
_ENTITY_FIELDS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    ("related_ips", "ip", _uuid_for_ip),
    ("related_users", "user", _uuid_for_user),
    ("related_hosts", "host", _uuid_for_host),
    ("related_domains", "domain", _uuid_for_domain),
)


RangeArg = Annotated[Literal["1h", "6h", "24h", "7d"], Query(description="Window size")]
ResolutionArg = Annotated[
    Literal["1m", "5m", "15m", "1h"] | None,
    Query(description="Bucket size (defaults to smallest allowed)"),
]


def _extract_entities(events: list[SeerflowEvent]) -> list[EntitySearchResult]:
    """Extract unique entity references from events, stamping UUIDs."""
    seen: set[tuple[str, str]] = set()
    results: list[EntitySearchResult] = []
    for event in events:
        for field_name, entity_type, resolver in _ENTITY_FIELDS:
            for value in getattr(event, field_name):
                key = (entity_type, value)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    entity_uuid = resolver(value)
                except (ValueError, TypeError):
                    _log.debug(
                        "Skipping malformed %s value in search: %r",
                        entity_type,
                        value,
                    )
                    continue
                results.append(
                    EntitySearchResult(
                        entity_type=entity_type,
                        entity_value=value,
                        entity_uuid=entity_uuid,
                    ),
                )
    return results


@router.get(
    "/entities/search",
    response_model=list[EntitySearchResult],
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(list_limit)
async def search_entities(
    request: Request,
    storage: Storage,
    q: str = Query(..., min_length=1, max_length=256, description="Search query"),
) -> list[EntitySearchResult]:
    """Search entities by value or UUID.

    UUID-shaped queries short-circuit to EventQuery(entity_uuid=...) and
    return only entities matching the queried UUID. Otherwise falls back
    to LogStore.search_text and extracts entity references from results.

    Only FR-036 pivot types (ip, user, host, domain) carry ``entity_uuid``
    in search results — a UUID query for a process/file/hash entity will
    return an empty list even if events reference it.
    """
    try:
        parsed_uuid: _uuid_mod.UUID | None = _uuid_mod.UUID(q)
    except ValueError:
        parsed_uuid = None

    if parsed_uuid is not None:
        target = str(parsed_uuid)
        # Match the fallback search_text(limit=100) ceiling. Callers should
        # pivot to /entities/{uuid}/timeline for full history.
        page = await storage.log_store.query_events(
            EventQuery(entity_uuid=target, limit=100),
        )
        all_entities = _extract_entities(list(page.items))
        return [r for r in all_entities if r.entity_uuid == target]

    events = await storage.log_store.search_text(q, limit=100)
    return _extract_entities(events)


@router.get(
    "/entities/{entity_uuid}/timeline",
    response_model=EntityTimelineResponse,
    responses={429: {"description": "Rate limit exceeded"}},
)
@limiter.limit(detail_limit)
async def get_entity_timeline(
    request: Request,
    entity_uuid: _uuid_mod.UUID,
    entity_store: Annotated[EntityStore, Depends(require_entity_store)],
    start_ns: Annotated[int | None, Query(ge=0, le=_MAX_TIMESTAMP_NS)] = None,
    end_ns: Annotated[int | None, Query(ge=0, le=_MAX_TIMESTAMP_NS)] = None,
    source_type: Annotated[str | None, Query(max_length=64)] = None,
    severity_min: Annotated[int | None, Query(ge=0, le=6)] = None,
    limit: Annotated[int, Query(ge=1, le=10_000)] = 1_000,
) -> EntityTimelineResponse:
    """Return cross-source timeline + related entities for an entity UUID."""
    try:
        time_range = _coerce_time_range(start_ns, end_ns)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="start_ns must be <= end_ns",
        ) from exc

    entity_uuid_str = str(entity_uuid)
    events, related = await asyncio.gather(
        entity_store.get_timeline(
            entity_uuid=entity_uuid_str,
            time_range=time_range,
            source_type=source_type,
            severity_min=severity_min,
            limit=limit,
        ),
        entity_store.get_related(entity_uuid=entity_uuid_str),
    )

    return EntityTimelineResponse(
        entity_uuid=entity_uuid_str,
        events=[EventResponse.from_event(e) for e in events],
        related=[EntityRelationResponse.from_relation(r) for r in related],
        total=len(events),
    )


@router.get(
    "/entities/{entity_uuid}/risk-history",
    response_model=RiskHistoryResponse,
    responses={
        422: {"description": "Invalid UUID / range / resolution"},
        429: {"description": "Rate limit exceeded"},
    },
)
@limiter.limit(list_limit)
async def get_entity_risk_history(
    request: Request,
    entity_uuid: _uuid_mod.UUID,
    storage: Storage,
    range: RangeArg = "1h",  # noqa: A002 -- matches public query param name
    resolution: ResolutionArg = None,
) -> RiskHistoryResponse:
    """Return a bucketed risk-score series for an entity (S-060.F1)."""
    resolved_resolution = resolution or default_resolution(range)
    if resolved_resolution not in allowed_resolutions(range):
        raise HTTPException(
            status_code=422,
            detail=(
                f"resolution {resolved_resolution!r} not allowed for range {range!r}"
            ),
        )

    range_ns = RANGE_NS[range]
    res_ns = RESOLUTION_NS[resolved_resolution]
    # Align ``now_ns`` to the resolution boundary so the helper yields exactly
    # ``range_ns / res_ns`` dense buckets (mirrors anomaly_timeline.query's
    # ``end_idx_aligned`` behaviour).
    now_ns = (time.time_ns() // res_ns) * res_ns
    entity_uuid_str = str(entity_uuid)

    alert_page = await storage.alert_store.query_alerts(
        AlertQuery(
            entity_uuid=entity_uuid_str,
            time_range=TimeRange(start_ns=now_ns - range_ns, end_ns=now_ns),
            limit=_ALERT_QUERY_LIMIT,
        )
    )

    items = _bucket_alerts(
        list(alert_page.items),
        now_ns=now_ns,
        range_ns=range_ns,
        res_ns=res_ns,
    )

    return RiskHistoryResponse(
        meta=RiskHistoryMetaResponse(
            range=range,
            resolution=resolved_resolution,
            alert_count_truncated=alert_page.total > len(alert_page.items),
        ),
        items=items,
    )


@router.get(
    "/entities/{entity_uuid}/baseline",
    responses={
        404: {"description": "Unknown entity or warming up"},
        422: {"description": "Invalid UUID"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "UEBA disabled"},
    },
)
@limiter.limit(list_limit)
async def get_entity_baseline(
    request: Request,
    entity_uuid: _uuid_mod.UUID,
) -> JSONResponse:
    """Return the current UEBA baseline for ``entity_uuid``.

    Response contract:

    - 503 ``{"detail": "UEBA disabled"}`` — baseline store not configured
      (mirrors ``require_entity_store`` for missing backends).
    - 404 ``{"detail": "unknown entity"}`` — store configured, entity never seen.
    - 404 ``{"status": "warming_up", ...}`` — seen but not past warmup gates.
    - 200 — warm baseline payload.
    """
    store = getattr(request.app.state, "baseline_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="UEBA disabled")
    baseline = store.get(str(entity_uuid))
    if baseline is None:
        raise HTTPException(status_code=404, detail="unknown entity")
    if not baseline.warmup_complete:
        days_observed = (baseline.last_seen_ns - baseline.first_seen_ns) / (86_400 * 1_000_000_000)
        return JSONResponse(
            status_code=404,
            content={
                "status": "warming_up",
                "events_observed": baseline.event_count,
                "events_required": store.params.warmup_min_events,
                "days_observed": days_observed,
                "days_required": store.params.warmup_days,
            },
        )
    ueba_engine = getattr(request.app.state, "ueba_engine", None)
    last_score_payload: dict[str, float] | None = None
    if ueba_engine is not None:
        last = ueba_engine.last_score(str(entity_uuid))
        if last is not None:
            last_score_payload = msgspec.to_builtins(last)
    return JSONResponse(
        status_code=200,
        content={
            "entity_uuid": baseline.entity_uuid,
            "entity_type": baseline.entity_type,
            "first_seen_ns": baseline.first_seen_ns,
            "last_seen_ns": baseline.last_seen_ns,
            "event_count": baseline.event_count,
            "warmup_complete": baseline.warmup_complete,
            "hours": list(baseline.hours),
            "source_ips": [list(pair) for pair in baseline.source_ips],
            "volume_ema_min": baseline.volume_ema_min,
            "volume_ema_hour": baseline.volume_ema_hour,
            "volume_last_ns": baseline.volume_last_ns,
            "templates": [list(pair) for pair in baseline.templates],
            "last_score": last_score_payload,
        },
    )
