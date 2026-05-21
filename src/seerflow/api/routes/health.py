"""GET /api/v1/health -- comprehensive service health check (S-080).

Returns 200 when all components are healthy, 503 when degraded. Same
status contract as the legacy aiohttp health endpoint (S-217), plus the
S-080 comprehensive envelope mandated by FR-047:

- ``uptime_seconds``, ``event_rate_per_sec``, ``active_sources``,
  ``model_count`` (from the in-process pipeline metrics provider);
- ``alert_count_24h`` (cached for 5 s to keep repeated probes cheap);
- ``memory_bytes`` (process RSS + ML model estimate);
- ``latency_ms`` (rolling ``p50``/``p95``/``p99`` per pipeline stage from
  the :class:`StageLatencyTracker`);
- ``detection`` and ``feedback`` (legacy aiohttp parity, preserved).

The handler is deliberately defensive: every optional dependency degrades
to a zero / empty / sentinel value rather than propagating a 500, because
container orchestrators rely on this endpoint for liveness checks.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import resource
import sys
import time
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request, Response

from seerflow.api.deps import (
    DetectionEngines,
    StorageDeps,
    get_alert_dispatcher,
    get_baseline_store,
    get_connection_manager,
    get_engines,
    get_explanation_cache,
    get_health_state,
    get_hunt_cache,
    get_kill_chain_tracker,
    get_otlp_sink,
    get_pagerduty_sink,
    get_pipeline_metrics_provider,
    get_receiver_manager,
    get_risk_register,
    get_rule_suggestion_cache,
    get_stage_latency_tracker,
    get_storage,
    get_window_buffer,
)
from seerflow.api.metrics import compute_uptime_rate
from seerflow.api.schemas import HealthResponse
from seerflow.models.query import AlertQuery, TimeRange
from seerflow.utils.log_sanitize import sanitize_exception
from seerflow.utils.memory_bounds import collect_memory_bounds

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import AlertDispatcher
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.pagerduty import PagerDutySink
    from seerflow.api.latency import StageLatencyTracker
    from seerflow.api.metrics import MetricsProvider
    from seerflow.api.ws import ConnectionManager
    from seerflow.correlation.kill_chain import KillChainTracker
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.llm.explanation.cache import ExplanationCache
    from seerflow.llm.hunt.cache import HuntCache
    from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
    from seerflow.receivers.manager import ReceiverManager
    from seerflow.ueba.store import BaselineStore

_log = logging.getLogger("seerflow.api.health")

router = APIRouter(tags=["system"])

_HEALTHY_VALUES = frozenset(
    {
        "running",
        "connected",
        "ok",
        "ready",
        # S-070: intentional absence of an optional component (e.g. LLM not
        # configured) is healthy. Only "degraded" maps to HTTP 503.
        "disabled",
    }
)

# Module-level alias for the platform string so tests can monkeypatch the
# RSS-unit branch via ``monkeypatch.setattr(health, "_PLATFORM", ...)``
# without poking ``sys.platform`` (which has surprising interactions with
# other modules that cache it at import time).
_PLATFORM: str = sys.platform

# Alert-count cache TTL (seconds). Each request returns the cached value
# when it is younger than this window. 5 s is short enough to keep the
# dashboard fresh while preventing back-to-back ``query_alerts`` calls
# under load (Kubernetes ``livenessProbe`` defaults to 10 s).
_ALERT_COUNT_TTL_S: float = 5.0
# 24 hours in nanoseconds (the unit used by ``TimeRange`` throughout the
# storage layer).
_ONE_DAY_NS: int = 24 * 3600 * 1_000_000_000
# S-233: server-side processing-duration header. The health route measures
# the wall-clock cost of its own handler body and emits it (float ms) on
# this header so callers/tests can budget the *endpoint's* work (FR-047)
# rather than the client round-trip, which is dominated by host scheduler
# noise under full-suite parallel + coverage load.
_PROCESS_TIME_HEADER: Final[str] = "X-Process-Time-Ms"

HealthState = Annotated[dict[str, str], Depends(get_health_state)]
Engines = Annotated[DetectionEngines, Depends(get_engines)]
Storage = Annotated[StorageDeps, Depends(get_storage)]
MetricsProviderDep = Annotated["MetricsProvider | None", Depends(get_pipeline_metrics_provider)]
LatencyTrackerDep = Annotated["StageLatencyTracker | None", Depends(get_stage_latency_tracker)]
# S-082: memory-bounds audit dependencies. Each defaults to ``None``; the
# route never instantiates these components — it only reads what is
# already wired on ``app.state``.
BaselineStoreDep = Annotated["BaselineStore | None", Depends(get_baseline_store)]
WindowBufferDep = Annotated["EntityWindowBuffer | None", Depends(get_window_buffer)]
RiskRegisterDep = Annotated["RiskRegister | None", Depends(get_risk_register)]
KillChainDep = Annotated["KillChainTracker | None", Depends(get_kill_chain_tracker)]
ReceiverManagerDep = Annotated["ReceiverManager | None", Depends(get_receiver_manager)]
AlertDispatcherDep = Annotated["AlertDispatcher | None", Depends(get_alert_dispatcher)]
OtlpSinkDep = Annotated["OtlpSink | None", Depends(get_otlp_sink)]
PagerDutySinkDep = Annotated["PagerDutySink | None", Depends(get_pagerduty_sink)]
ConnectionManagerDep = Annotated["ConnectionManager | None", Depends(get_connection_manager)]
ExplanationCacheDep = Annotated["ExplanationCache | None", Depends(get_explanation_cache)]
HuntCacheDep = Annotated["HuntCache | None", Depends(get_hunt_cache)]
RuleSuggestionCacheDep = Annotated[
    "RuleSuggestionCache | None", Depends(get_rule_suggestion_cache)
]


@dataclasses.dataclass
class _AlertCountCache:
    """In-memory TTL cache for the rolling 24 h alert count.

    Lives on ``app.state`` for the lifetime of the FastAPI app. The
    ``asyncio.Lock`` is held across the ``query_alerts`` await so a burst
    of concurrent probes serializes onto a single store call rather than
    each issuing its own (closes the TOCTOU window between the freshness
    check and the write).
    """

    value: int = 0
    stored_at_monotonic: float = -1.0
    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)

    def fresh(self, now_monotonic: float) -> bool:
        return (
            self.stored_at_monotonic >= 0.0
            and now_monotonic - self.stored_at_monotonic < _ALERT_COUNT_TTL_S
        )

    def set(self, now_monotonic: float, value: int) -> None:
        self.value = value
        self.stored_at_monotonic = now_monotonic


def _get_alert_count_cache(request: Request) -> _AlertCountCache:
    """Return the per-app alert-count cache.

    The cache is pre-initialized in ``create_api_app`` (S-080); the
    ``getattr`` fallback only fires when a test instantiates the route on
    a bare ``FastAPI()`` without going through the factory.
    """
    cache: _AlertCountCache | None = getattr(request.app.state, "health_alert_count_cache", None)
    if cache is None:
        cache = _AlertCountCache()
        request.app.state.health_alert_count_cache = cache
    return cache


def _get_rss_bytes() -> int:
    """Return process RSS in bytes.

    ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` returns KiB on Linux and
    bytes on macOS — normalize to bytes so the wire contract is platform-
    independent. Any exception (e.g. ``resource`` unavailable on some
    sandboxed environments) degrades to ``0``.
    """
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except Exception as exc:
        _log.debug("rss unavailable: %s", exc)
        return 0
    raw = int(usage.ru_maxrss)
    if _PLATFORM.startswith("linux"):
        return raw * 1024
    # Darwin (and conservatively any other platform) reports bytes.
    return raw


def _model_memory_bytes(engines: DetectionEngines) -> int:
    """Best-effort estimate of bytes held by the ML ensemble."""
    if engines.ensemble is None:
        return 0
    try:
        health = engines.ensemble.get_health()
    except Exception:
        return 0
    raw = health.get("estimated_memory_bytes", 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def _alert_count_24h(storage: StorageDeps, cache: _AlertCountCache) -> int:
    """Return the rolling 24 h alert count, cached for ``_ALERT_COUNT_TTL_S``.

    The lock is held across the freshness check and the underlying
    ``query_alerts`` await, so concurrent probes serialize onto a single
    store call rather than each issuing its own. Sentinel ``-1`` is
    returned when the alert store query fails; the health endpoint still
    answers 200 in that case so a transient storage blip does not flap
    probes.
    """
    async with cache.lock:
        if cache.fresh(time.monotonic()):
            return cache.value
        now_ns = time.time_ns()
        time_range = TimeRange(start_ns=max(0, now_ns - _ONE_DAY_NS), end_ns=now_ns)
        try:
            page = await storage.alert_store.query_alerts(
                AlertQuery(time_range=time_range, limit=1)
            )
        except Exception as exc:
            _log.warning("alert_count_24h query failed: %s", sanitize_exception(exc))
            return -1
        total = int(page.total)
        cache.set(time.monotonic(), total)
        return total


@router.get("/health", response_model=HealthResponse)
async def get_health(
    # surfaces every audited component; collapsing them under a single
    # injected bag would hide the contract from the dependency tree.
    request: Request,
    response: Response,
    health_state: HealthState,
    engines: Engines,
    storage: Storage,
    metrics_provider: MetricsProviderDep,
    latency_tracker: LatencyTrackerDep,
    baseline_store: BaselineStoreDep,
    window_buffer: WindowBufferDep,
    risk_register: RiskRegisterDep,
    kill_chain: KillChainDep,
    receiver_manager: ReceiverManagerDep,
    alert_dispatcher: AlertDispatcherDep,
    otlp_sink: OtlpSinkDep,
    pagerduty_sink: PagerDutySinkDep,
    ws_manager: ConnectionManagerDep,
    explanation_cache: ExplanationCacheDep,
    hunt_cache: HuntCacheDep,
    rule_suggestion_cache: RuleSuggestionCacheDep,
) -> HealthResponse:
    """Return comprehensive service health status (S-080 + S-082)."""
    # S-233: measure the route's own processing duration. ``perf_counter``
    # is monotonic; the delta captured at ``return`` is the endpoint's
    # work only, immune to client-side scheduler / coverage-tracing noise.
    _t0 = time.perf_counter()
    all_healthy = all(v in _HEALTHY_VALUES for v in health_state.values())
    status: Literal["healthy", "degraded"] = "healthy" if all_healthy else "degraded"
    if not all_healthy:
        response.status_code = 503

    detection: dict[str, Any] | None = (
        engines.ensemble.get_health() if engines.ensemble is not None else None
    )
    # ``StorageDeps.alert_store`` is non-Optional by contract; feedback is
    # always populated.
    feedback: dict[str, int] = await storage.alert_store.get_feedback_stats()

    uptime_seconds = 0.0
    event_rate_per_sec = 0.0
    active_sources = 0
    model_count = 0
    if metrics_provider is not None:
        try:
            snapshot = metrics_provider()
            uptime_seconds, event_rate_per_sec = compute_uptime_rate(
                snapshot.started_monotonic,
                snapshot.total_events_processed,
            )
            active_sources = int(snapshot.active_sources)
            model_count = int(snapshot.model_count)
        except Exception as exc:
            _log.warning("pipeline metrics provider failed: %s", sanitize_exception(exc))

    cache = _get_alert_count_cache(request)
    alert_count_24h = await _alert_count_24h(storage, cache)

    latency_ms: dict[str, dict[str, float | int]] = (
        latency_tracker.snapshot() if latency_tracker is not None else {}
    )

    memory_bytes: dict[str, int] = {
        "rss": _get_rss_bytes(),
        "models": _model_memory_bytes(engines),
    }

    # S-082: per-component memory-bound snapshot. Pure read of in-process
    # accessors; degrades to an empty dict when no component is wired.
    memory_bounds = collect_memory_bounds(
        ensemble=engines.ensemble,
        baseline_store=baseline_store,
        window_buffer=window_buffer,
        risk_register=risk_register,
        kill_chain=kill_chain,
        receiver_manager=receiver_manager,
        alert_dispatcher=alert_dispatcher,
        otlp_sink=otlp_sink,
        pagerduty_sink=pagerduty_sink,
        websocket_manager=ws_manager,
        latency_tracker=latency_tracker,
        explanation_cache=explanation_cache,
        hunt_cache=hunt_cache,
        rule_suggestion_cache=rule_suggestion_cache,
    )

    result = HealthResponse(
        status=status,
        components=health_state,
        detection=detection,
        feedback=feedback,
        uptime_seconds=uptime_seconds,
        event_rate_per_sec=event_rate_per_sec,
        active_sources=active_sources,
        model_count=model_count,
        alert_count_24h=alert_count_24h,
        memory_bytes=memory_bytes,
        latency_ms=latency_ms,
        # MemoryBoundsReport is a TypedDict — at runtime it is a plain
        # dict, so we widen the nested type explicitly. Pydantic accepts
        # the structural match.
        memory_bounds={
            k: {"current": v["current"], "max": v["max"], "evictions": v["evictions"]}
            for k, v in memory_bounds.items()
        },
    )
    # S-233: emit server-side processing duration (ms) before returning, on
    # both the 200 and 503 paths. The value is the route's own work only —
    # immune to client-side scheduler noise under full-suite parallel load.
    response.headers[_PROCESS_TIME_HEADER] = f"{(time.perf_counter() - _t0) * 1000.0:.3f}"
    return result
