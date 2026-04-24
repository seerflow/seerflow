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
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_engines,
    get_storage,
)
from seerflow.api.limits import limiter, list_limit, sigma_upload_limit
from seerflow.api.schemas import (
    SigmaRuleDetail,
    SigmaRuleListResponse,
    SigmaRuleSummary,
    SigmaRuleToggleRequest,
    SigmaRuleUploadRequest,
    SigmaRuleValidationResult,
)
from seerflow.models.query import AlertQuery, TimeRange
from seerflow.sigma.engine import SigmaRuleCollisionError
from seerflow.sigma.validator import SigmaRuleValidationError

if TYPE_CHECKING:
    from seerflow.sigma.engine import SigmaEngine

router = APIRouter(tags=["sigma"], prefix="/sigma")

Storage = Annotated[StorageDeps, Depends(get_storage)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]

# 24h alert-count window scan ceiling. Mirrors attack/coverage: a single
# bounded scan beats N per-rule round-trips; AlertStore enforces 10000 cap.
_ALERT_SCAN_LIMIT = 10_000


def _require_engine(engines: DetectionEngines) -> SigmaEngine:
    if engines.sigma_engine is None:
        raise HTTPException(status_code=503, detail="sigma_engine not configured")
    return engines.sigma_engine


async def _alert_counts_24h(storage: StorageDeps) -> dict[str, int]:
    """Group sigma alerts by ``rule_name`` over the trailing 24h window."""
    end_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    start_ns = end_ns - 24 * 3600 * 1_000_000_000
    page = await storage.alert_store.query_alerts(
        AlertQuery(
            time_range=TimeRange(start_ns=start_ns, end_ns=end_ns),
            alert_type="sigma",
            page=1,
            limit=_ALERT_SCAN_LIMIT,
        )
    )
    counts: dict[str, int] = {}
    for alert in page.items:
        counts[alert.rule_name] = counts.get(alert.rule_name, 0) + 1
    return counts


def _matches_filters(
    rule: dict[str, object],
    *,
    category: str | None,
    severity: int | None,
    logsource_product: str | None,
    enabled: bool | None,
    source: str | None,
    search: str | None,
) -> bool:
    ls_key = rule["logsource_key"]
    assert isinstance(ls_key, list)
    if category and ls_key[0] != category:
        return False
    if severity is not None and rule["severity"] != severity:
        return False
    if logsource_product and ls_key[1] != logsource_product:
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


@router.get("/rules", response_model=SigmaRuleListResponse)
@limiter.limit(list_limit)
async def list_rules(
    request: Request,
    storage: Storage,
    engines: Engines,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    category: Annotated[str | None, Query(max_length=64)] = None,
    severity: Annotated[int | None, Query(ge=0, le=24)] = None,
    logsource_product: Annotated[str | None, Query(max_length=64)] = None,
    enabled: Annotated[bool | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> SigmaRuleListResponse:
    """Return loaded Sigma rules with filters and per-rule 24h alert counts."""
    engine = _require_engine(engines)
    counts_24h = await _alert_counts_24h(storage)
    all_rules = engine.list_rules()
    filtered = [
        r
        for r in all_rules
        if _matches_filters(
            r,
            category=category,
            severity=severity,
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
    return SigmaRuleListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/rules/{rule_id}", response_model=SigmaRuleDetail)
@limiter.limit(list_limit)
async def get_rule(
    request: Request,
    rule_id: str,
    storage: Storage,
    engines: Engines,
) -> SigmaRuleDetail:
    engine = _require_engine(engines)
    rule = next((r for r in engine.list_rules() if r["rule_id"] == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    counts_24h = await _alert_counts_24h(storage)
    return _build_detail(rule, counts_24h.get(str(rule["title"]), 0))


@router.patch("/rules/{rule_id}", response_model=SigmaRuleDetail)
@limiter.limit(list_limit)
async def patch_rule(
    request: Request,
    rule_id: str,
    body: SigmaRuleToggleRequest,
    storage: Storage,
    engines: Engines,
) -> SigmaRuleDetail:
    """Toggle ``enabled`` on a single rule. Idempotent. 404 if not loaded."""
    engine = _require_engine(engines)
    if not any(r["rule_id"] == rule_id for r in engine.list_rules()):
        raise HTTPException(status_code=404, detail="rule not found")
    engine.set_enabled(rule_id, body.enabled)
    state_store = getattr(request.app.state, "sigma_state_store", None)
    if state_store is not None:
        await state_store.set_enabled(rule_id, body.enabled)
    rule = next(r for r in engine.list_rules() if r["rule_id"] == rule_id)
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

    try:
        meta = engine.validate_rule(body.yaml)
    except SigmaRuleValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    rid = str(meta["rule_id"])
    persist_path = upload_dir / f"{rid}.yml"
    try:
        engine.add_rule(body.yaml, persist_path, source_kind="custom_uploaded")
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

    rule = next(r for r in engine.list_rules() if r["rule_id"] == rid)
    counts_24h = await _alert_counts_24h(storage)
    return JSONResponse(
        status_code=201,
        content=_build_detail(rule, counts_24h.get(str(rule["title"]), 0)).model_dump(),
    )
