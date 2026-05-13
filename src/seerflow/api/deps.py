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
    from seerflow.api.anomaly_timeline import AnomalyTimelineRing
    from seerflow.api.metrics import MetricsProvider
    from seerflow.detection.ensemble import DetectionEnsemble
    from seerflow.llm.explanation.service import AlertExplanationService
    from seerflow.llm.hunt.service import NaturalLanguageHuntService
    from seerflow.llm.rule_suggestion.service import RuleSuggestionService
    from seerflow.models.alert import CorrelationRule
    from seerflow.sigma.engine import SigmaEngine
    from seerflow.storage.protocols import AlertStore, EntityStore, LogStore


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
