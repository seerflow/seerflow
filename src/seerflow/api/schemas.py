"""Pydantic response and request models for the Seerflow REST API.

These models define the JSON contract for all API endpoints. Each model
that wraps a msgspec struct has a ``from_*`` classmethod for conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_serializer, field_validator

from seerflow.utils.text import NOTE_MAX_LENGTH, sanitise_feedback_note

if TYPE_CHECKING:
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.feedback import FeedbackEvent
    from seerflow.models.query import EntityRelation

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

    @field_serializer("timestamp_ns", when_used="json")
    def _serialize_timestamp_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)

    @field_serializer("observed_ns", when_used="json")
    def _serialize_observed_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)

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
    feedback_note: str = ""
    mitre_tactics: list[str] = Field(default_factory=list)
    mitre_techniques: list[str] = Field(default_factory=list)

    @field_serializer("timestamp_ns", when_used="json")
    def _serialize_timestamp_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-194).

        ``when_used="json"`` keeps ``model_dump(mode="python")`` returning the
        native ``int`` so the field's type annotation stays honest for
        in-process callers; only ``model_dump(mode="json")`` (and the FastAPI
        response path) emits a string.
        """
        return str(v)

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
            feedback_note=alert.feedback_note,
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
    """Pipeline statistics — combines persistent counts and live metrics.

    Persistent counts (``total_events``, ``total_alerts``, ``alerts_by_severity``,
    ``feedback_stats``) come from the storage backend. Live metrics
    (``uptime_seconds``, ``event_rate_per_sec``, ``total_events_processed``,
    ``active_sources``, ``model_count``) come from the in-process pipeline
    metrics provider. Live metric fields default to ``0`` when no provider
    is wired (test mode, API running without a pipeline).
    """

    total_events: int
    total_alerts: int
    alerts_by_severity: dict[str, int]
    feedback_stats: dict[str, int]
    uptime_seconds: float = 0.0
    event_rate_per_sec: float = 0.0
    total_events_processed: int = 0
    active_sources: int = 0
    model_count: int = 0


class FeedbackRequest(BaseModel):
    """Request body for alert feedback submission.

    ``origin`` is constrained to values a real HTTP client can legitimately
    claim. ``"cli"`` is excluded here because CLI invocations bypass HTTP
    entirely (they call ``process_feedback`` directly), so accepting ``"cli"``
    on the HTTP boundary would let any client forge that source label and
    corrupt audit-log integrity. The storage layer's ``FeedbackOrigin`` type
    and SQLite ``CHECK`` constraint still accept ``"cli"`` for rows written
    by the in-process CLI path.
    """

    feedback: Literal["tp", "fp"]
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)
    origin: Literal["dashboard", "api"] = "api"

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        """Strip C0 controls and DEL via the shared feedback-note sanitiser."""
        if v is None:
            return None
        return sanitise_feedback_note(v)


class FeedbackEventResponse(BaseModel):
    """JSON representation of a single feedback audit-log entry."""

    id: int
    feedback: Literal["tp", "fp"]
    note: str
    origin: Literal["dashboard", "cli", "api"]
    submitted_at_ns: int

    @field_serializer("submitted_at_ns", when_used="json")
    def _serialize_submitted_at_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety."""
        return str(v)

    @classmethod
    def from_event(cls, ev: FeedbackEvent) -> FeedbackEventResponse:
        """Convert a FeedbackEvent storage struct to a Pydantic response model."""
        return cls(
            id=ev.id,
            feedback=ev.feedback,
            note=ev.note,
            origin=ev.origin,
            submitted_at_ns=ev.submitted_at_ns,
        )


class EntitySearchResult(BaseModel):
    """A single entity match from search."""

    entity_type: str
    entity_value: str
    entity_uuid: str


class EntityRelationResponse(BaseModel):
    """A related entity in the entity graph."""

    entity_uuid: str
    entity_type: str
    entity_value: str
    relation_type: str

    @classmethod
    def from_relation(cls, relation: EntityRelation) -> EntityRelationResponse:
        """Convert a dataclass EntityRelation to a Pydantic response model."""
        return cls(
            entity_uuid=relation.entity_uuid,
            entity_type=relation.entity_type,
            entity_value=relation.entity_value,
            relation_type=relation.relation_type,
        )


class EntityTimelineResponse(BaseModel):
    """Entity timeline detail: events + related entities.

    ``total`` is the count of returned events in this page, equal to
    ``len(events)``. When ``total`` equals the handler's ``limit`` query
    parameter, the result may be truncated — callers should narrow the
    time range or raise ``limit`` to retrieve more.
    """

    entity_uuid: str
    events: list[EventResponse]
    related: list[EntityRelationResponse]
    total: int


class TimelineBucketResponse(BaseModel):
    """One bucket in the anomaly timeline series."""

    bucket_start_ns: int = Field(ge=0)
    max_score: float | None
    avg_score: float | None
    event_count: int = Field(ge=0)
    upper_threshold: float | None
    alert_count: int = Field(ge=0)

    @field_serializer("bucket_start_ns", when_used="json")
    def _serialize_bucket_start_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)


class TimelineMetaResponse(BaseModel):
    """Metadata for the anomaly timeline response."""

    range: Literal["1h", "6h", "24h", "7d"]
    resolution: Literal["1m", "5m", "15m", "1h"]
    source: str | None
    alert_count_truncated: bool = False


class TimelineResponse(BaseModel):
    """Top-level response for GET /api/v1/anomaly/timeline."""

    meta: TimelineMetaResponse
    items: list[TimelineBucketResponse]


class RiskBucketResponse(BaseModel):
    """One bucket of the per-entity risk-history series (S-060.F1)."""

    bucket_start_ns: int = Field(ge=0)
    points: float = Field(ge=0.0)
    alert_count: int = Field(ge=0)
    top_rule_name: str = ""

    @field_serializer("bucket_start_ns", when_used="json")
    def _serialize_bucket_start_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)


class RiskHistoryMetaResponse(BaseModel):
    """Echo of the resolved (range, resolution) plus truncation flag."""

    range: Literal["1h", "6h", "24h", "7d"]
    resolution: Literal["1m", "5m", "15m", "1h"]
    alert_count_truncated: bool = False


class RiskHistoryResponse(BaseModel):
    """Envelope for GET /api/v1/entities/{uuid}/risk-history."""

    meta: RiskHistoryMetaResponse
    items: list[RiskBucketResponse]


class AttackCoverageCell(BaseModel):
    """One (tactic, technique) cell in the ATT&CK coverage matrix."""

    tactic: str
    technique: str
    rule_count: int = Field(ge=0)
    alert_count: int = Field(ge=0)
    covered: bool
    detected: bool
    rule_names: list[str] = Field(default_factory=list)


class AttackCoverageTactic(BaseModel):
    """All technique cells grouped under a single tactic."""

    tactic: str
    tactic_display_name: str
    techniques: list[AttackCoverageCell] = Field(default_factory=list)


class AttackCoverageSummary(BaseModel):
    """Aggregate totals across the whole coverage response.

    ``total_rules_with_attack_tags`` and ``total_alerts_matched`` count
    **cell hits**, not unique rules/alerts: a rule tagged with two
    tactics and two techniques contributes 4 to ``total_rules_with_attack_tags``,
    and an alert with the same shape contributes 4 to
    ``total_alerts_matched``. This matches how the matrix is rendered
    (each cell displays a per-cell count) but differs from "number of
    distinct alerts in the window."
    """

    total_techniques_covered: int = Field(ge=0)
    total_techniques_detected: int = Field(ge=0)
    total_rules_with_attack_tags: int = Field(ge=0)
    total_alerts_matched: int = Field(ge=0)


class AttackCoverageResponse(BaseModel):
    """Top-level ATT&CK coverage matrix response.

    ``window_since`` and ``window_until`` are ISO-8601 strings produced
    by ``datetime.isoformat()`` on a UTC-aware ``datetime``. Offsets are
    emitted as ``+00:00`` (RFC 3339 canonical), not the ``Z`` shorthand.
    Callers parsing these should accept both via ``datetime.fromisoformat``.
    """

    window_since: str
    window_until: str
    tactics: list[AttackCoverageTactic]
    summary: AttackCoverageSummary


# ---------------------------------------------------------------------------
# Sigma rules management (S-151)
# ---------------------------------------------------------------------------


class SigmaRuleSummary(BaseModel):
    """One row in the Sigma rules table."""

    rule_id: str
    title: str
    description: str = ""
    severity: int
    logsource_key: list[str]
    attack_tactics: list[str]
    attack_techniques: list[str]
    enabled: bool
    source: str
    match_count_lifetime: int
    last_fired_ns: int | None = None
    alert_count_24h: int = 0


class SigmaRuleDetail(SigmaRuleSummary):
    """Single rule view including raw YAML source."""

    yaml_source: str


class SigmaRuleToggleRequest(BaseModel):
    enabled: bool


class SigmaRuleUploadRequest(BaseModel):
    yaml: str = Field(..., max_length=65_536)


class SigmaRuleValidationResult(BaseModel):
    """Outcome of dry-run validation. ``valid=False`` carries error fields."""

    valid: bool
    rule_id: str | None = None
    title: str | None = None
    logsource_key: list[str] | None = None
    stage: Literal["yaml", "schema", "compile"] | None = None
    message: str | None = None
    line: int | None = None
    column: int | None = None
    field: str | None = None


class SigmaRuleTimelineBucket(BaseModel):
    """One hourly bucket in the per-rule firing timeline."""

    bucket_start_ns: int = Field(..., description="UTC ns at the start of the bucket")
    count: int = Field(..., ge=0)


class SigmaRuleTimelineResponse(BaseModel):
    """Dense 24-bucket grid for a single Sigma rule's last-24h firing trend."""

    buckets: list[SigmaRuleTimelineBucket]
