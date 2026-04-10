"""Pydantic response and request models for the Seerflow REST API.

These models define the JSON contract for all API endpoints. Each model
that wraps a msgspec struct has a ``from_*`` classmethod for conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent

_T = TypeVar("_T")


class EventResponse(BaseModel):
    """JSON representation of a SeerflowEvent."""

    event_id: str
    timestamp_ns: int
    observed_ns: int
    severity_id: int
    severity_text: str
    source_type: str
    message: str
    template_id: int
    entity_refs: list[str] = Field(default_factory=list)

    @classmethod
    def from_event(cls, event: SeerflowEvent) -> EventResponse:
        """Convert a msgspec SeerflowEvent to a Pydantic response model."""
        return cls(
            event_id=str(event.event_id),
            timestamp_ns=event.timestamp_ns,
            observed_ns=event.observed_ns,
            severity_id=int(event.severity_id),
            severity_text=event.severity_id.text,
            source_type=event.source_type,
            message=event.message,
            template_id=event.template_id,
            entity_refs=list(event.entity_refs),
        )


class AlertResponse(BaseModel):
    """JSON representation of an Alert."""

    alert_id: str
    timestamp_ns: int
    alert_type: str
    rule_name: str
    severity: int
    risk_score: float
    entity_uuid: str
    entity_type: str
    entity_value: str
    message: str
    dedup_count: int = 1
    feedback: str | None = None
    mitre_tactics: list[str] = Field(default_factory=list)
    mitre_techniques: list[str] = Field(default_factory=list)

    @classmethod
    def from_alert(cls, alert: Alert) -> AlertResponse:
        """Convert a msgspec Alert to a Pydantic response model."""
        return cls(
            alert_id=alert.alert_id,
            timestamp_ns=alert.timestamp_ns,
            alert_type=alert.alert_type,
            rule_name=alert.rule_name,
            severity=int(alert.severity_id),
            risk_score=alert.risk_score,
            entity_uuid=alert.entity_uuid,
            entity_type=alert.entity_type,
            entity_value=alert.entity_value,
            message=alert.description,
            dedup_count=alert.dedup_count,
            feedback=alert.feedback or None,
            mitre_tactics=list(alert.mitre_tactics),
            mitre_techniques=list(alert.mitre_techniques),
        )


class PaginatedResponse(BaseModel, Generic[_T]):
    """Paginated result envelope for list endpoints."""

    items: list[_T]
    total: int
    page: int
    limit: int
    has_next: bool


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded"]
    components: dict[str, str]


class StatsResponse(BaseModel):
    """Basic pipeline statistics."""

    total_events: int
    total_alerts: int
    alerts_by_severity: dict[str, int]
    feedback_stats: dict[str, int]


class FeedbackRequest(BaseModel):
    """Request body for alert feedback submission."""

    feedback: Literal["tp", "fp"]


class EntitySearchResult(BaseModel):
    """A single entity match from search."""

    entity_type: str
    entity_value: str
