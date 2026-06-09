"""Pydantic response and request models for the Seerflow REST API.

These models define the JSON contract for all API endpoints. Each model
that wraps a msgspec struct has a ``from_*`` classmethod for conversion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_serializer, field_validator

from seerflow.utils.text import NOTE_MAX_LENGTH, sanitise_feedback_note

if TYPE_CHECKING:
    from seerflow.llm.explanation.result import ExplanationResult
    from seerflow.llm.hunt.result import HuntResult
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
    # IoC enrichment (S-069). ``None`` when the event has no matches; a list
    # of summary dicts otherwise — see ``_ioc_match_payload`` in
    # seerflow.threat_intel.enricher for the canonical shape.
    ioc_matches: list[dict[str, Any]] | None = None

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
        raw = event.attributes.get("ioc_matches") if event.attributes else None
        ioc_matches = list(raw) if isinstance(raw, list) and raw else None
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
            ioc_matches=ioc_matches,
        )


def entity_path_for(event: SeerflowEvent) -> dict[str, str | None]:
    """Derive a ``{src, dst}`` entity-path hop from a SeerflowEvent (S-338).

    Precedence: ``related_users`` → ``related_hosts`` → ``related_ips``. The
    first non-empty category wins; ``src`` takes the first value and
    ``dst`` takes the second when present, otherwise ``None``. Returns
    ``{src: None, dst: None}`` when the event carries no related entities
    so the caller can decide whether to omit the field upstream.

    This intentionally mirrors the ``_entity_summary`` precedence used by
    the WebSocket emitter (``src/seerflow/api/ws.py``) so the detail rail
    and the live event stream agree on which entity gets surfaced.
    """
    for values in (event.related_users, event.related_hosts, event.related_ips):
        if values:
            src = values[0]
            dst = values[1] if len(values) > 1 else None
            return {"src": src, "dst": dst}
    return {"src": None, "dst": None}


class ContributingEventResponse(BaseModel):
    """One row in the alert-detail "correlated events" grid (S-338).

    Hydrated server-side from the matching ``SeerflowEvent`` records pointed
    at by ``Alert.contributing_events``. The frontend uses ``severity_text``
    to drive row tinting and ``entity_path`` for the `src → dst` column.
    """

    event_id: str
    timestamp_ns: int
    message: str
    severity_text: str
    entity_path: dict[str, str | None] = Field(default_factory=dict)

    @field_serializer("timestamp_ns", when_used="json")
    def _serialize_timestamp_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-194 pattern)."""
        return str(v)

    @classmethod
    def from_event(cls, event: SeerflowEvent) -> ContributingEventResponse:
        return cls(
            event_id=str(event.event_id),
            timestamp_ns=event.timestamp_ns,
            message=event.message,
            severity_text=event.severity_id.text,
            entity_path=entity_path_for(event),
        )


class AlertResponse(BaseModel):
    """JSON representation of an Alert.

    ``contributing_events`` is populated only by the alert-detail endpoint
    (S-338) — the list / WS payload omits it.
    """

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
    # S-338: only the alert-detail endpoint hydrates this — the list / WS
    # paths leave it unset. ``None`` (= JSON omission) keeps every other
    # endpoint payload byte-identical.
    contributing_events: list[ContributingEventResponse] | None = None

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
    def from_alert(
        cls,
        alert: Alert,
        *,
        contributing_events: list[ContributingEventResponse] | None = None,
    ) -> AlertResponse:
        """Convert a msgspec Alert to a Pydantic response model.

        ``contributing_events`` is optional — pass it only from the
        alert-detail endpoint after hydrating the matching SeerflowEvents.
        """
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
            contributing_events=contributing_events,
        )


class AlertExplanationResponse(BaseModel):
    """JSON representation of an ``ExplanationResult`` (S-071, FR-056)."""

    alert_id: str
    summary: str
    anomaly_rationale: str
    contributing_events: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool
    truncated: bool

    @field_serializer("generated_at_ns", when_used="json")
    def _serialize_generated_at_ns(self, v: int) -> str:
        """Render epoch-ns as a JSON string for JS bigint safety."""
        return str(v)

    @classmethod
    def from_result(cls, result: ExplanationResult) -> AlertExplanationResponse:
        """Convert an ``ExplanationResult`` dataclass to a Pydantic model."""
        return cls(
            alert_id=result.alert_id,
            summary=result.summary,
            anomaly_rationale=result.anomaly_rationale,
            contributing_events=list(result.contributing_events),
            recommended_next_steps=list(result.recommended_next_steps),
            model=result.model,
            generated_at_ns=result.generated_at_ns,
            latency_ms=result.latency_ms,
            cached=result.cached,
            truncated=result.truncated,
        )


class NLHuntRequest(BaseModel):
    """``POST /api/v1/hunt`` request body (S-072, FR-057).

    ``query`` is the natural-language question. Validation length matches
    the default ``hunt_max_query_chars`` on ``LLMConfig`` so over-budget
    queries are rejected at the API boundary, before the prompt builder
    re-validates.
    """

    query: str = Field(min_length=1, max_length=16_384)


class NLHuntResponse(BaseModel):
    """``POST /api/v1/hunt`` response (S-072, FR-057)."""

    query: str
    filters: dict[str, Any]
    events: list[EventResponse] = Field(default_factory=list)
    total: int
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool
    truncated: bool

    @field_serializer("generated_at_ns", when_used="json")
    def _serialize_generated_at_ns(self, v: int) -> str:
        """Render epoch-ns as a JSON string for JS bigint safety."""
        return str(v)

    @classmethod
    def from_result(cls, result: HuntResult) -> NLHuntResponse:
        """Convert a ``HuntResult`` dataclass to the JSON response model."""
        return cls(
            query=result.query,
            filters=dict(result.filters),
            events=[EventResponse.from_event(e) for e in result.events],
            total=result.total,
            model=result.model,
            generated_at_ns=result.generated_at_ns,
            latency_ms=result.latency_ms,
            cached=result.cached,
            truncated=result.truncated,
        )


class PaginatedResponse(BaseModel, Generic[_T]):
    """Paginated result envelope for list endpoints."""

    items: list[_T]
    total: int
    page: int
    limit: int
    has_next: bool


class HealthResponse(BaseModel):
    """Health check response (S-080 comprehensive envelope).

    ``detection`` and ``feedback`` mirror the legacy aiohttp health
    contract (S-217): when a ``DetectionEnsemble`` and ``AlertStore``
    are wired into the FastAPI app, the route populates them with
    ``ensemble.get_health()`` and ``await alert_store.get_feedback_stats()``
    respectively. Both default to ``None`` for tests that exercise the
    legacy minimal envelope.

    S-080 adds the comprehensive fields required by FR-047:
    ``uptime_seconds``, ``event_rate_per_sec``, ``active_sources``,
    ``model_count``, ``alert_count_24h``, ``memory_bytes`` and
    ``latency_ms``. Every new field has a default so existing tests and
    clients keyed on the legacy minimal envelope keep working.
    """

    status: Literal["healthy", "degraded"]
    components: dict[str, str]
    detection: dict[str, Any] | None = None
    feedback: dict[str, int] | None = None
    uptime_seconds: float = 0.0
    event_rate_per_sec: float = 0.0
    active_sources: int = 0
    model_count: int = 0
    # ``-1`` is the "unknown" sentinel when the alert store query fails;
    # otherwise the total number of alerts written in the last 24 hours.
    alert_count_24h: int = 0
    memory_bytes: dict[str, int] = Field(default_factory=dict)
    # ``{stage: {p50, p95, p99, count}}`` — ``p50``/``p95``/``p99`` are
    # ``float`` ms, ``count`` is ``int``. Empty when no tracker is wired or
    # no samples have been recorded yet.
    latency_ms: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    # S-082: per-component memory-bound snapshot. Each entry is
    # ``{component_key: {"current": int, "max": int, "evictions": int}}``.
    # Empty when no audited component is wired on ``app.state``. Component
    # keys are stable strings documented in
    # :func:`seerflow.utils.memory_bounds.collect_memory_bounds`.
    memory_bounds: dict[str, dict[str, int]] = Field(default_factory=dict)


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
    # Per-feed TAXII counters (S-067). ``None`` when threat_intel is
    # disabled or no metrics provider is wired. Each value is a serialised
    # ``TAXIIFeedMetrics`` dict (see seerflow.threat_intel.metrics).
    taxii: dict[str, dict[str, Any]] | None = None
    # IoC matcher snapshot (S-068). ``None`` when the matcher is disabled
    # or no metrics provider is wired. Serialised ``IoCMatcherMetrics``
    # dataclass (see seerflow.threat_intel.matcher).
    ioc_matcher: dict[str, object] | None = None
    # IoC enrichment counters (S-069). ``None`` when the matcher is disabled
    # or no metrics provider is wired. Serialised ``IoCEnrichmentMetrics``
    # struct (see seerflow.threat_intel.enricher).
    ioc_enrichment: dict[str, object] | None = None


class PluginInfo(BaseModel):
    """One row of the plugin inventory (S-370 AC-4).

    ``id`` is the namespaced ``group:name`` identifier; ``protocol`` is the
    public Protocol the plugin satisfies (``Receiver`` / ``DeliveryTarget`` /
    ``StorageBackend``); ``status`` is the lifecycle state (``loaded`` /
    ``started`` / ``stopped`` / ``failed``).
    """

    id: str
    version: str
    protocol: str
    status: str


class PluginInventoryResponse(BaseModel):
    """Inventory of all loaded plugins returned by ``GET /api/v1/plugins``."""

    plugins: list[PluginInfo]
    total: int


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

    @field_serializer("bucket_start_ns", when_used="json")
    def _serialize_bucket_start_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199).

        FE valibot schema expects ``v.bigint()`` post-revival, but the
        ``BIGINT_KEYS`` walker in ``frontend/src/lib/api.ts`` only revives
        when the wire value is a JSON string. Without this serializer the
        sparkline silently fails to render for every rule.
        """
        return str(v)


class SigmaRuleTimelineResponse(BaseModel):
    """Dense 24-bucket grid for a single Sigma rule's last-24h firing trend."""

    buckets: list[SigmaRuleTimelineBucket]


class RuleSuggestionPattern(BaseModel):
    """One eligible pattern in the ``GET /sigma/rule-suggestions`` list (S-100).

    Mirrors :class:`seerflow.llm.rule_suggestion.aggregator.PatternFeedbackRow`.
    ``most_recent_tp_ns`` is serialised as a JSON string for JS bigint safety,
    matching the convention on :class:`SigmaRuleTimelineBucket`.
    """

    pattern_key: str
    tp_count: int
    most_recent_tp_ns: int
    contributing_alert_ids: list[str]

    @field_serializer("most_recent_tp_ns", when_used="json")
    def _serialize_most_recent_tp_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)


class RuleSuggestionResponse(BaseModel):
    """One drafted Sigma rule suggestion (S-100).

    Carries the YAML body, the structured validator verdict, and the
    metadata the dashboard needs (model, latency, cache hit). Maps from
    :class:`seerflow.llm.rule_suggestion.result.RuleSuggestionResult`.
    """

    pattern_key: str
    tp_count: int
    yaml: str
    title: str
    logsource_key: list[str]
    validation_stage: Literal["ok", "yaml", "schema", "compile"]
    validation_message: str
    contributing_alert_ids: list[str]
    model: str
    generated_at_ns: int
    latency_ms: float
    cached: bool

    @field_serializer("generated_at_ns", when_used="json")
    def _serialize_generated_at_ns(self, v: int) -> str:
        """Render as JSON string for JS bigint safety (S-199)."""
        return str(v)
