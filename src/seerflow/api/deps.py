"""Dependency injection for the FastAPI API layer.

StorageDeps bundles storage Protocol instances. Depends providers extract
them from FastAPI app.state so route handlers stay decoupled from wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import AlertDispatcher
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.pagerduty import PagerDutySink
    from seerflow.api.anomaly_timeline import AnomalyTimelineRing
    from seerflow.api.latency import StageLatencyTracker
    from seerflow.api.metrics import MetricsProvider
    from seerflow.api.ws import ConnectionManager
    from seerflow.correlation.kill_chain import KillChainTracker
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.llm.explanation.cache import ExplanationCache
    from seerflow.llm.explanation.service import AlertExplanationService
    from seerflow.llm.hunt.cache import HuntCache
    from seerflow.llm.hunt.service import NaturalLanguageHuntService
    from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
    from seerflow.llm.rule_suggestion.service import RuleSuggestionService
    from seerflow.models.alert import CorrelationRule
    from seerflow.plugins.lifecycle import PluginInventory
    from seerflow.receivers.manager import ReceiverManager
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore
    from seerflow.ueba.store import BaselineStore


@dataclass(frozen=True, slots=True)
class StorageDeps:
    """Bundle of storage backends injected into the FastAPI app."""

    log_store: LogStore
    alert_store: AlertStore
    entity_store: EntityStore | None = None


def get_storage(request: Request) -> StorageDeps:
    """FastAPI Depends provider -- retrieves StorageDeps from app.state."""
    return request.app.state.storage  # type: ignore[no-any-return]


def get_health_state(request: Request) -> dict[str, str]:
    """FastAPI Depends provider -- retrieves mutable health state dict."""
    return request.app.state.health_state  # type: ignore[no-any-return]


_MAX_TIMESTAMP_NS = 2**63 - 1  # SQLite int64 ceiling (~year 2262)


def parse_timestamp_ns(iso_str: str) -> int:
    """Convert an ISO-8601 string to nanoseconds since epoch.

    Assumes UTC if no timezone info is present.
    Raises ValueError if the result is out of int64 range.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    ns = int(dt.timestamp() * 1_000_000_000)
    if ns < 0 or ns > _MAX_TIMESTAMP_NS:
        msg = f"Timestamp out of supported range: {iso_str!r}"
        raise ValueError(msg)
    return ns


def require_entity_store(
    storage: StorageDeps = Depends(get_storage),  # noqa: B008
) -> EntityStore:
    """FastAPI Depends -- return entity_store or 503 if missing."""
    if storage.entity_store is None:
        raise HTTPException(
            status_code=503,
            detail="entity_store not configured",
        )
    return storage.entity_store


@dataclass(frozen=True, slots=True)
class DetectionEngines:
    """Snapshot of detection engines injected into the FastAPI app.

    Hot-reloads managed by ``seerflow.correlation.reloader`` are NOT
    reflected here — the snapshot is captured at ``create_api_app`` time.
    Restart the process to refresh rule counts in the coverage API.

    ``ensemble`` (S-217) carries the live ``DetectionEnsemble`` so the
    health route can mirror the legacy aiohttp contract by calling
    ``ensemble.get_health()``.
    """

    sigma_engine: SigmaEngine | None = None
    correlation_rules: tuple[CorrelationRule, ...] = ()
    ensemble: DetectionEnsemble | None = None


def get_engines(request: Request) -> DetectionEngines:
    """FastAPI Depends provider -- retrieve DetectionEngines from app.state."""
    return request.app.state.engines  # type: ignore[no-any-return]


def get_anomaly_timeline_ring(request: Request) -> AnomalyTimelineRing:
    """Return the AnomalyTimelineRing stored on app.state.

    Raises RuntimeError if the ring was not configured via ``create_api_app``
    or an explicit test setup. No lazy fallback — a missing ring is a wiring
    bug, not a runtime condition to paper over.
    """
    ring: AnomalyTimelineRing | None = getattr(request.app.state, "anomaly_timeline_ring", None)
    if ring is None:
        msg = "anomaly_timeline_ring not configured on app.state"
        raise RuntimeError(msg)
    return ring


def get_pipeline_metrics_provider(request: Request) -> MetricsProvider | None:
    """FastAPI Depends provider — returns the pipeline metrics provider or None.

    Returns the callable stashed at ``app.state.pipeline_metrics_provider``,
    or ``None`` if the attribute is missing (test mode / API running without
    a pipeline). Callers are responsible for the ``None`` fallback.
    """
    provider: MetricsProvider | None = getattr(
        request.app.state, "pipeline_metrics_provider", None
    )
    return provider


def get_plugin_inventory(request: Request) -> PluginInventory:
    """FastAPI Depends provider — return the loaded plugin inventory (S-370).

    Reads the :class:`~seerflow.plugins.lifecycle.PluginInventory` stashed at
    ``app.state.plugins`` by the pipeline / ``create_api_app``. When the
    attribute is missing (test mode / API running without a pipeline, or
    plugins disabled) an empty inventory is returned so the
    ``GET /api/v1/plugins`` route always responds with a well-formed body
    rather than 500-ing.
    """
    from seerflow.plugins.lifecycle import PluginInventory
    from seerflow.plugins.records import LoadedPlugins

    inventory: PluginInventory | None = getattr(request.app.state, "plugins", None)
    if inventory is None:
        return PluginInventory(LoadedPlugins())
    return inventory


def get_explanation_service(request: Request) -> AlertExplanationService | None:
    """FastAPI Depends provider — returns the LLM explanation service or None.

    Returns the service stashed at ``app.state.explanation_service`` (S-071),
    or ``None`` if the attribute is missing (LLM disabled / degraded / API
    running without a pipeline). Callers translate ``None`` to a 503
    response with the ``health_state["llm"]`` status.
    """
    service: AlertExplanationService | None = getattr(
        request.app.state, "explanation_service", None
    )
    return service


def get_hunt_service(request: Request) -> NaturalLanguageHuntService | None:
    """FastAPI Depends provider — returns the NL hunt service or None.

    Returns the service stashed at ``app.state.hunt_service`` (S-072), or
    ``None`` if the attribute is missing (LLM disabled / degraded / API
    running without a pipeline). Callers translate ``None`` to a 503
    response with the ``health_state["llm"]`` status.
    """
    service: NaturalLanguageHuntService | None = getattr(request.app.state, "hunt_service", None)
    return service


def get_stage_latency_tracker(request: Request) -> StageLatencyTracker | None:
    """FastAPI Depends provider — returns the rolling latency tracker or None.

    Returns the ``StageLatencyTracker`` stashed at
    ``app.state.stage_latency_tracker`` (S-080), or ``None`` when the
    attribute is missing (test mode / API running without a pipeline).
    The health route degrades to an empty ``latency_ms`` field when this
    is ``None``.
    """
    tracker: StageLatencyTracker | None = getattr(request.app.state, "stage_latency_tracker", None)
    return tracker


def get_baseline_store(request: Request) -> BaselineStore | None:
    """FastAPI Depends — return the UEBA baseline store or ``None`` (S-082)."""
    store: BaselineStore | None = getattr(request.app.state, "baseline_store", None)
    return store


def get_window_buffer(request: Request) -> EntityWindowBuffer | None:
    """FastAPI Depends — return the entity-temporal window buffer (S-082)."""
    buf: EntityWindowBuffer | None = getattr(request.app.state, "window_buffer", None)
    return buf


def get_risk_register(request: Request) -> RiskRegister | None:
    """FastAPI Depends — return the per-entity risk register (S-082)."""
    reg: RiskRegister | None = getattr(request.app.state, "risk_register", None)
    return reg


def get_kill_chain_tracker(request: Request) -> KillChainTracker | None:
    """FastAPI Depends — return the kill-chain tracker (S-082)."""
    kc: KillChainTracker | None = getattr(request.app.state, "kill_chain_tracker", None)
    return kc


def get_receiver_manager(request: Request) -> ReceiverManager | None:
    """FastAPI Depends — return the receiver intake manager (S-082)."""
    mgr: ReceiverManager | None = getattr(request.app.state, "receiver_manager", None)
    return mgr


def get_alert_dispatcher(request: Request) -> AlertDispatcher | None:
    """FastAPI Depends — return the alert dispatcher (S-082)."""
    dispatcher: AlertDispatcher | None = getattr(request.app.state, "alert_dispatcher", None)
    return dispatcher


def get_otlp_sink(request: Request) -> OtlpSink | None:
    """FastAPI Depends — return the OTLP alert sink (S-082)."""
    sink: OtlpSink | None = getattr(request.app.state, "otlp_sink", None)
    return sink


def get_pagerduty_sink(request: Request) -> PagerDutySink | None:
    """FastAPI Depends — return the PagerDuty alert sink (S-082)."""
    sink: PagerDutySink | None = getattr(request.app.state, "pagerduty_sink", None)
    return sink


def get_connection_manager(request: Request) -> ConnectionManager | None:
    """FastAPI Depends — return the WebSocket connection manager (S-082)."""
    mgr: ConnectionManager | None = getattr(request.app.state, "ws_manager", None)
    return mgr


def get_explanation_cache(request: Request) -> ExplanationCache | None:
    """FastAPI Depends — return the explanation LRU+TTL cache (S-082)."""
    cache: ExplanationCache | None = getattr(request.app.state, "explanation_cache", None)
    return cache


def get_hunt_cache(request: Request) -> HuntCache | None:
    """FastAPI Depends — return the natural-language hunt cache (S-082)."""
    cache: HuntCache | None = getattr(request.app.state, "hunt_cache", None)
    return cache


def get_rule_suggestion_cache(request: Request) -> RuleSuggestionCache | None:
    """FastAPI Depends — return the rule-suggestion cache (S-082)."""
    cache: RuleSuggestionCache | None = getattr(request.app.state, "rule_suggestion_cache", None)
    return cache


def get_rule_suggestion_service(request: Request) -> RuleSuggestionService | None:
    """FastAPI Depends provider — returns the rule-suggestion service or None.

    Returns the service stashed at ``app.state.rule_suggestion_service`` (S-100),
    or ``None`` if the attribute is missing (LLM disabled / degraded / API
    running without a pipeline). Callers translate ``None`` to a 503
    response with the ``health_state["llm"]`` status — same pattern as the
    explanation + hunt services.
    """
    service: RuleSuggestionService | None = getattr(
        request.app.state, "rule_suggestion_service", None
    )
    return service
