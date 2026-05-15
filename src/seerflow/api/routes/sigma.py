"""Sigma rule management REST endpoints (S-151).

Endpoints (mounted under ``/api/v1`` by ``create_api_app``):

* ``GET    /sigma/rules``           — paginated list, filterable
* ``GET    /sigma/rules/{rule_id}`` — single rule with full YAML
* ``PATCH  /sigma/rules/{rule_id}`` — toggle ``enabled``
* ``POST   /sigma/rules``           — upload custom rule (or ``?dry_run=true``)

Authz: no auth layer in Seerflow today (Sprint 14+); this surface trusts
the same operator boundary as ``/api/v1/config``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi import Path as FPath
from fastapi.responses import JSONResponse

from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_engines,
    get_health_state,
    get_rule_suggestion_service,
    get_storage,
)
from seerflow.api.limits import detail_limit, limiter, list_limit, sigma_upload_limit
from seerflow.api.schemas import (
    PaginatedResponse,
    RuleSuggestionPattern,
    RuleSuggestionResponse,
    SigmaRuleDetail,
    SigmaRuleSummary,
    SigmaRuleTimelineBucket,
    SigmaRuleTimelineResponse,
    SigmaRuleToggleRequest,
    SigmaRuleUploadRequest,
    SigmaRuleValidationResult,
)
from seerflow.models.query import TimeRange
from seerflow.sigma.engine import SigmaRuleCollisionError
from seerflow.sigma.ids import compute_rule_id
from seerflow.sigma.validator import SigmaRuleValidationError, validate_yaml

if TYPE_CHECKING:
    from seerflow.llm.rule_suggestion.service import RuleSuggestionService
    from seerflow.sigma.engine import SigmaEngine

router = APIRouter(tags=["sigma"], prefix="/sigma")

Storage = Annotated[StorageDeps, Depends(get_storage)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]
RuleSuggestionDep = Annotated["RuleSuggestionService | None", Depends(get_rule_suggestion_service)]
HealthStateDep = Annotated[dict[str, str], Depends(get_health_state)]

# Path regex for ``pattern_key`` — only the characters
# ``derive_pattern_key`` ever produces. Any caller-supplied value that
# doesn't match returns 422 from FastAPI before reaching the service.
_PATTERN_KEY_REGEX = r"^[a-z0-9_:.-]{1,128}$"

# Timeline bucket size + count. The endpoint returns exactly 24 hourly
# buckets across the trailing 24h window; both are pinned today (only
# ``bucket="hour"`` and ``window="24h"`` accepted) and externalised here
# so a future v2 extension does not duplicate magic numbers.
_HOUR_NS: int = 3600 * 1_000_000_000
_TIMELINE_BUCKET_COUNT: int = 24

# Operator upload ceiling. 5 uploads/min for a year is ~2.5M rules; the
# bundled set is ~60. 1000 leaves ample room for legitimate growth and
# bounds disk fill if rate-limit is bypassed.
_MAX_CUSTOM_UPLOADS = 1000

# severity_in cardinality cap. The OTel severity scale defines 24 levels
# (0 reserved + 1-24); 25 leaves headroom for "0" while bounding the
# per-request parse loop so a pathological client cannot DOS the filter.
_MAX_SEVERITY_IN = 25


def _require_engine(engines: DetectionEngines) -> SigmaEngine:
    if engines.sigma_engine is None:
        raise HTTPException(status_code=503, detail="sigma_engine not configured")
    return engines.sigma_engine


async def _alert_counts_24h(storage: StorageDeps) -> dict[str, int]:
    """Group sigma alerts by ``rule_name`` over the trailing 24h window.

    Pushes the aggregation to SQL via ``count_alerts_grouped`` — no
    result-set cap, so high-volume deployments are no longer silently
    undercounted, and the full alert payload is no longer decoded just
    to tally counts (S-229 / SEE-240).
    """
    end_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    start_ns = end_ns - 24 * 3600 * 1_000_000_000
    return await storage.alert_store.count_alerts_grouped(
        alert_type="sigma",
        time_range=TimeRange(start_ns=start_ns, end_ns=end_ns),
        group_by="rule_name",
    )


def _parse_severity_in(values: list[str] | None) -> list[int] | None:
    """Parse repeated ``severity_in`` query values into a bounded int list.

    Empty strings are treated as a no-op (so ``?severity_in=`` does not
    narrow). Anything outside the SeverityLevel range (0-24, mirroring the
    OTel severity scale used elsewhere in the API) is rejected with 422
    rather than silently dropped, so client bugs surface loudly.
    """
    if not values:
        return None
    if len(values) > _MAX_SEVERITY_IN:
        raise HTTPException(
            status_code=422,
            detail=f"severity_in accepts at most {_MAX_SEVERITY_IN} values",
        )
    parsed: list[int] = []
    for raw in values:
        token = raw.strip()
        if not token:
            continue
        try:
            sev = int(token)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"severity_in: invalid integer {raw!r}",
            ) from exc
        if sev < 0 or sev > 24:
            raise HTTPException(
                status_code=422,
                detail=f"severity_in: {sev} out of range [0, 24]",
            )
        parsed.append(sev)
    return parsed or None


def _matches_filters(
    rule: dict[str, object],
    *,
    category: str | None,
    severity_in: list[int] | None,
    logsource_product: str | None,
    enabled: bool | None,
    source: str | None,
    search: str | None,
) -> bool:
    ls_key = cast("list[str]", rule["logsource_key"])
    if category and (not ls_key or ls_key[0] != category):
        return False
    if severity_in and rule["severity"] not in severity_in:
        return False
    if logsource_product and (len(ls_key) < 2 or ls_key[1] != logsource_product):
        return False
    if enabled is not None and rule["enabled"] != enabled:
        return False
    if source and rule["source"] != source:
        return False
    return not (search and search.lower() not in str(rule["title"]).lower())


def _build_summary(rule: dict[str, object], alert_count_24h: int) -> SigmaRuleSummary:
    return SigmaRuleSummary(
        rule_id=cast("str", rule["rule_id"]),
        title=cast("str", rule["title"]),
        description=cast("str", rule["description"]),
        severity=cast("int", rule["severity"]),
        logsource_key=cast("list[str]", rule["logsource_key"]),
        attack_tactics=cast("list[str]", rule["attack_tactics"]),
        attack_techniques=cast("list[str]", rule["attack_techniques"]),
        enabled=cast("bool", rule["enabled"]),
        source=cast("str", rule["source"]),
        match_count_lifetime=cast("int", rule["match_count_lifetime"]),
        last_fired_ns=cast("int | None", rule["last_fired_ns"]),
        alert_count_24h=alert_count_24h,
    )


def _build_detail(rule: dict[str, object], alert_count_24h: int) -> SigmaRuleDetail:
    return SigmaRuleDetail(
        **_build_summary(rule, alert_count_24h).model_dump(),
        yaml_source=str(rule["yaml_source"]),
    )


@router.get("/rules", response_model=PaginatedResponse[SigmaRuleSummary])
@limiter.limit(list_limit)
async def list_rules(
    request: Request,
    storage: Storage,
    engines: Engines,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    category: Annotated[str | None, Query(max_length=64)] = None,
    severity_in: Annotated[
        list[str] | None,
        Query(
            description=(
                "Filter rules whose severity is in this set. "
                "Repeat the param: ?severity_in=4&severity_in=5. "
                "Empty value = no filter."
            ),
        ),
    ] = None,
    logsource_product: Annotated[str | None, Query(max_length=64)] = None,
    enabled: Annotated[bool | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> PaginatedResponse[SigmaRuleSummary]:
    """Return loaded Sigma rules with filters and per-rule 24h alert counts."""
    engine = _require_engine(engines)
    counts_24h = await _alert_counts_24h(storage)
    parsed_severity_in = _parse_severity_in(severity_in)
    all_rules = engine.list_rules()
    filtered = [
        r
        for r in all_rules
        if _matches_filters(
            r,
            category=category,
            severity_in=parsed_severity_in,
            logsource_product=logsource_product,
            enabled=enabled,
            source=source,
            search=search,
        )
    ]
    total = len(filtered)
    start = (page - 1) * limit
    page_items = filtered[start : start + limit]
    items = [_build_summary(r, counts_24h.get(str(r["title"]), 0)) for r in page_items]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        has_next=(page * limit) < total,
    )


@router.get("/rules/{rule_id}", response_model=SigmaRuleDetail)
@limiter.limit(list_limit)
async def get_rule(
    request: Request,
    rule_id: Annotated[str, FPath(max_length=36)],
    storage: Storage,
    engines: Engines,
) -> SigmaRuleDetail:
    engine = _require_engine(engines)
    rule = engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    counts_24h = await _alert_counts_24h(storage)
    return _build_detail(rule, counts_24h.get(str(rule["title"]), 0))


@router.get(
    "/rules/{rule_id}/timeline",
    response_model=SigmaRuleTimelineResponse,
)
@limiter.limit(list_limit)
async def get_rule_timeline(
    request: Request,
    rule_id: Annotated[str, FPath(max_length=36)],
    storage: Storage,
    engines: Engines,
    bucket: Annotated[Literal["hour"], Query()] = "hour",
    window: Annotated[Literal["24h"], Query()] = "24h",
) -> SigmaRuleTimelineResponse:
    """Return a dense 24-hour, 1-bucket-per-hour firing trend for *rule_id*.

    ``bucket`` and ``window`` are typed as single-value ``Literal``s today;
    keeping them as query params (rather than dropping them) lets a future
    v2 widen the enum without breaking the URL shape. The returned grid is
    always exactly 24 buckets, ascending, with zero-count buckets filled
    in client-side-friendly form so the dashboard sparkline never has to
    densify itself. Returns 404 only when the rule id is not loaded by
    the engine; an empty alert window is a 200 with 24 zero buckets.
    """
    engine = _require_engine(engines)
    rule = engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    now_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    # snap "now" up to the next hour boundary so the 24-bucket grid covers
    # 24 complete hours [end_ns - 24h, end_ns) — no partial trailing cell
    end_ns = -(-now_ns // _HOUR_NS) * _HOUR_NS  # ceil-divide
    start_ns = end_ns - _TIMELINE_BUCKET_COUNT * _HOUR_NS
    rows = await storage.alert_store.count_alerts_bucketed(
        alert_type="sigma",
        # title doubles as rule_name on the alerts table (see _rule_to_summary invariant)
        rule_name=cast("str", rule["title"]),
        time_range=TimeRange(start_ns=start_ns, end_ns=end_ns),
        bucket_ns=_HOUR_NS,
    )
    counts = dict(rows)
    grid = [
        SigmaRuleTimelineBucket(
            bucket_start_ns=start_ns + i * _HOUR_NS,
            count=counts.get(start_ns + i * _HOUR_NS, 0),
        )
        for i in range(_TIMELINE_BUCKET_COUNT)
    ]
    return SigmaRuleTimelineResponse(buckets=grid)


@router.patch("/rules/{rule_id}", response_model=SigmaRuleDetail)
@limiter.limit(list_limit)
async def patch_rule(
    request: Request,
    rule_id: Annotated[str, FPath(max_length=36)],
    body: SigmaRuleToggleRequest,
    storage: Storage,
    engines: Engines,
) -> SigmaRuleDetail:
    """Toggle ``enabled`` on a single rule. Idempotent. 404 if not loaded."""
    engine = _require_engine(engines)
    if engine.get_rule(rule_id) is None:
        raise HTTPException(status_code=404, detail="rule not found")
    engine.set_enabled(rule_id, body.enabled)
    state_store = getattr(request.app.state, "sigma_state_store", None)
    if state_store is not None:
        await state_store.set_enabled(rule_id, body.enabled)
    rule = engine.get_rule(rule_id)
    if rule is None:  # pragma: no cover - rule cannot disappear mid-request
        raise HTTPException(status_code=404, detail="rule not found")
    counts_24h = await _alert_counts_24h(storage)
    return _build_detail(rule, counts_24h.get(str(rule["title"]), 0))


@router.post(
    "/rules",
    response_model=None,
    responses={
        201: {"description": "Created"},
        409: {"description": "Rule ID collision"},
        422: {"description": "Validation failure or upload dir not configured"},
    },
)
@limiter.limit(sigma_upload_limit)
async def upload_rule(
    request: Request,
    body: SigmaRuleUploadRequest,
    storage: Storage,
    engines: Engines,
    dry_run: Annotated[bool, Query()] = False,
) -> JSONResponse | SigmaRuleValidationResult:
    """Validate (and optionally persist) a Sigma rule YAML payload.

    With ``?dry_run=true`` the payload is validated only — no disk write,
    no engine mutation. Returns ``SigmaRuleValidationResult`` either way.
    """
    engine = _require_engine(engines)
    config = getattr(request.app.state, "config", None)
    upload_dir_str: str | None = None
    if config is not None:
        upload_dir_str = config.detection.sigma_custom_upload_dir
    upload_dir = Path(upload_dir_str) if upload_dir_str else None

    if dry_run:
        try:
            meta = engine.validate_rule(body.yaml)
        except SigmaRuleValidationError as exc:
            return SigmaRuleValidationResult(
                valid=False,
                stage=exc.stage,  # type: ignore[arg-type]
                message=exc.message,
                line=exc.line,
                column=exc.column,
                field=exc.field,
            )
        return SigmaRuleValidationResult(
            valid=True,
            rule_id=cast("str", meta["rule_id"]),
            title=cast("str", meta["title"]),
            logsource_key=cast("list[str]", meta["logsource_key"]),
        )

    if upload_dir is None:
        raise HTTPException(status_code=422, detail="sigma_custom_upload_dir not configured")

    # Disk-fill cap: count current ``custom_uploaded`` rules before
    # accepting the new one. The bundled set is excluded so legitimate
    # operators are not blocked by the cap.
    uploaded_count = sum(1 for r in engine.list_rules() if r["source"] == "custom_uploaded")
    if uploaded_count >= _MAX_CUSTOM_UPLOADS:
        raise HTTPException(
            status_code=507,
            detail=f"upload limit reached ({_MAX_CUSTOM_UPLOADS} custom rules)",
        )

    # Validate once and pass the parsed rule through to ``add_rule`` so the
    # pipeline + compile chain runs a single time per upload.
    try:
        rule_obj = validate_yaml(body.yaml)
    except SigmaRuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rid = compute_rule_id(rule_obj)
    persist_path = upload_dir / f"{rid}.yml"
    try:
        engine.add_rule(
            body.yaml,
            persist_path,
            source_kind="custom_uploaded",
            prevalidated_rule=rule_obj,
        )
    except SigmaRuleCollisionError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "collision": True,
                "existing_rule_id": exc.rule_id,
                "existing_source": exc.existing_source,
            },
        )
    except OSError as exc:
        raise HTTPException(
            status_code=507,
            detail=f"failed to persist rule: {exc.strerror or exc}",
        ) from exc

    rule = engine.get_rule(rid)
    if rule is None:  # pragma: no cover - add_rule guarantees presence
        raise HTTPException(status_code=500, detail="rule disappeared after add")
    counts_24h = await _alert_counts_24h(storage)
    return JSONResponse(
        status_code=201,
        content=_build_detail(rule, counts_24h.get(str(rule["title"]), 0)).model_dump(),
    )


# --------------------------------------------------------------------------
# S-100 — Sigma rule suggestion from TP feedback (FR-066)
#
# Three endpoints expose the LLM-drafted rule-suggestion flow:
#
#   GET    /sigma/rule-suggestions             — list eligible patterns
#   POST   /sigma/rule-suggestions/{key}       — draft (or return cached)
#   DELETE /sigma/rule-suggestions/{key}       — invalidate cache after promotion
#
# All three return 503 with ``{"detail": "llm_not_ready", "status":
# health_state["llm"]}`` when the LLM backend is disabled or degraded.
# --------------------------------------------------------------------------


def _llm_not_ready(health_state: dict[str, str]) -> HTTPException:
    """Return a 503 envelope reflecting the live LLM health surface."""
    return HTTPException(
        status_code=503,
        detail={
            "detail": "llm_not_ready",
            "status": health_state.get("llm", "disabled"),
        },
    )


@router.get(
    "/rule-suggestions",
    response_model=PaginatedResponse[RuleSuggestionPattern],
    responses={
        429: {"description": "Rate limit exceeded"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(list_limit)
async def list_rule_suggestions(
    request: Request,  # required for slowapi
    service: RuleSuggestionDep,
    health_state: HealthStateDep,
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    limit: Annotated[int, Query(ge=1, le=200, description="Results per page")] = 50,
) -> PaginatedResponse[RuleSuggestionPattern]:
    """List patterns eligible for a Sigma rule suggestion (S-100, FR-066)."""
    if service is None:
        raise _llm_not_ready(health_state)

    rows = await service.list_eligible_patterns()
    total = len(rows)
    start = (page - 1) * limit
    end = start + limit
    items = [
        RuleSuggestionPattern(
            pattern_key=row.pattern_key,
            tp_count=row.tp_count,
            most_recent_tp_ns=row.most_recent_tp_ns,
            contributing_alert_ids=list(row.contributing_alert_ids),
        )
        for row in rows[start:end]
    ]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
        has_next=end < total,
    )


@router.post(
    "/rule-suggestions/{pattern_key}",
    response_model=RuleSuggestionResponse,
    responses={
        404: {"description": "Pattern no longer eligible"},
        422: {"description": "Invalid pattern_key"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "LLM backend failed"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(detail_limit)
async def draft_rule_suggestion(
    request: Request,  # required for slowapi
    pattern_key: Annotated[
        str,
        FPath(
            description="Pattern key (alert_type:rule_name:entity_type)",
            pattern=_PATTERN_KEY_REGEX,
            max_length=128,
        ),
    ],
    service: RuleSuggestionDep,
    health_state: HealthStateDep,
) -> RuleSuggestionResponse:
    """Generate (or return cached) Sigma rule suggestion for a TP-confirmed pattern."""
    if service is None:
        raise _llm_not_ready(health_state)

    try:
        result = await service.suggest(pattern_key)
    except TimeoutError:
        raise HTTPException(
            status_code=502,
            detail={"detail": "llm_timeout"},
        ) from None
    except Exception:
        # Any other backend error — propagate as a generic 502 so the
        # dashboard can grey out the suggestion. Detailed context is in
        # the server log (logged inside the service).
        raise HTTPException(
            status_code=502,
            detail={"detail": "llm_failed"},
        ) from None

    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": "pattern_not_eligible"},
        )

    return RuleSuggestionResponse(
        pattern_key=result.pattern_key,
        tp_count=result.tp_count,
        yaml=result.yaml,
        title=result.title,
        logsource_key=list(result.logsource_key),
        validation_stage=result.validation_stage,
        validation_message=result.validation_message,
        contributing_alert_ids=list(result.contributing_alert_ids),
        model=result.model,
        generated_at_ns=result.generated_at_ns,
        latency_ms=result.latency_ms,
        cached=result.cached,
    )


@router.delete(
    "/rule-suggestions/{pattern_key}",
    status_code=204,
    responses={
        422: {"description": "Invalid pattern_key"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "LLM not ready"},
    },
)
@limiter.limit(detail_limit)
async def invalidate_rule_suggestion(
    request: Request,  # required for slowapi
    pattern_key: Annotated[
        str,
        FPath(
            description="Pattern key (alert_type:rule_name:entity_type)",
            pattern=_PATTERN_KEY_REGEX,
            max_length=128,
        ),
    ],
    service: RuleSuggestionDep,
    health_state: HealthStateDep,
) -> Response:
    """Drop the cached suggestion for ``pattern_key``.

    Idempotent — returns 204 whether or not a cached entry existed. Used
    by the dashboard after the operator promotes the suggested rule via
    the existing ``POST /api/v1/sigma/rules`` upload route so the
    candidate list refreshes.
    """
    if service is None:
        raise _llm_not_ready(health_state)
    await service.invalidate(pattern_key)
    return Response(status_code=204)
