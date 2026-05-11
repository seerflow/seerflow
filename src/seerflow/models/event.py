"""SeerflowEvent — the core data model for the processing pipeline.

A frozen, GC-free msgspec.Struct designed for 10K+ events/sec throughput.
Every log event traverses the pipeline as an immutable SeerflowEvent instance.
Use ``msgspec.structs.replace()`` for functional updates.

The ``tag=True`` option adds a ``type`` discriminator field to serialized output,
enabling tagged-union decoding when multiple struct types share the same wire
channel (e.g., ``msgspec.json.decode(data, type=SeerflowEvent | Alert)``).
"""

import enum
import uuid

import msgspec

# Bounded type for event attribute values.
# Terminal scalars + one level of structured payloads (lists of
# string-keyed dicts of scalars + lists-of-strings) used by enrichment
# blocks like ``ioc_matches`` (S-069). Deeper structures must be
# encoded by the producer.
_AttrLeaf = str | int | float | bool | None
_AttrStructFieldValue = _AttrLeaf | list[str]
_AttrStruct = dict[str, _AttrStructFieldValue]
AttrValue = _AttrLeaf | list[_AttrStruct]


class SeverityLevel(int, enum.Enum):
    """Unified severity scale (0-6) mapping OTel, syslog, and ECS severities."""

    TRACE = 0
    INFORMATIONAL = 1
    NOTICE = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5
    FATAL = 6

    @property
    def text(self) -> str:
        """Human-readable severity label."""
        return self.name.capitalize()


# Public severity bounds — imported by api/ws.py and api/routes/alerts.py
# to prevent drift between REST and WebSocket validation.
SEVERITY_MIN: int = SeverityLevel.TRACE
SEVERITY_MAX: int = SeverityLevel.FATAL


class SeerflowEvent(msgspec.Struct, frozen=True, gc=False, tag=True):
    """Unified log event struct for the Seerflow processing pipeline.

    Merges four log schema standards:

    - OpenTelemetry LogRecord (nanosecond timestamps, trace context, severity 1-24)
    - Elastic Common Schema (event.kind/category/type/outcome hierarchy)
    - OCSF (numeric taxonomy: category_uid/class_uid/type_uid)
    - Sigma (logsource.category/product/service for detection rules)

    All dict fields use ``msgspec.field(default_factory=...)`` to avoid the
    mutable-default antipattern. Although msgspec copies defaults per instance,
    explicit factories make intent clear to contributors.

    Note: ``frozen=True`` prevents field re-binding but does not deep-freeze
    dict contents. Consumers should treat dict fields as read-only.

    OCSF invariant: ``type_uid = class_uid * 100 + activity_id``. Callers
    setting any of these three fields must set all three consistently.

    Entity fields: ``related_ips``, ``related_users``, ``related_hosts``,
    ``related_files``, ``related_domains``, ``related_processes`` carry raw
    extracted values.  ``entity_refs`` holds deterministic UUID5 strings
    resolved from the raw values (see ``resolve_entities``).

    ``related_hashes`` format: ``"<algo>:<lowercase-hex-digest>"``, e.g.
    ``"sha256:e3b0c44298fc1c14..."``  Validation is enforced at the
    ingestion boundary, not in this struct.
    """

    # Identity
    event_id: uuid.UUID
    timestamp_ns: int  # event time (nanoseconds since epoch)
    observed_ns: int  # pipeline receive time (nanoseconds since epoch)

    # Trace context (OTel)
    trace_id: str | None = None
    span_id: str | None = None

    # Severity (unified 0-6, validated via SeverityLevel enum)
    severity_id: SeverityLevel = SeverityLevel.INFORMATIONAL
    otel_severity: int = 9  # OTel SeverityNumber 1-24; 9 = INFO

    # Classification (ECS hierarchy)
    event_kind: str = "event"
    event_category: str = ""
    event_type: str = ""
    event_outcome: str = ""
    event_action: str = ""

    # OCSF numeric taxonomy
    category_uid: int = 0
    class_uid: int = 0
    type_uid: int = 0
    activity_id: int = 0  # OCSF activity; type_uid = class_uid * 100 + activity_id

    # Content
    message: str = ""
    body: msgspec.Raw | None = None  # Deferred decoding for arbitrary log payloads

    # Source tracking
    source_type: str = ""
    source_id: str = ""
    log_source_category: str = ""
    log_source_product: str = ""
    log_source_service: str = ""

    # Drain3 metadata
    template_id: int = -1  # -1 = no Drain3 template matched (sentinel, avoids Optional)
    template_str: str = ""
    template_params: tuple[str, ...] = ()

    # Entity references (UUID5 strings)
    entity_refs: tuple[str, ...] = ()
    related_ips: tuple[str, ...] = ()
    related_users: tuple[str, ...] = ()
    related_hosts: tuple[str, ...] = ()
    related_files: tuple[str, ...] = ()
    related_domains: tuple[str, ...] = ()
    related_processes: tuple[str, ...] = ()
    related_hashes: tuple[str, ...] = ()  # File/process hashes for IoC matching

    # MITRE ATT&CK
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()

    # Scores
    risk_score: float = 0.0
    confidence: float = 1.0
    anomaly_score: float = 0.0

    # Metadata
    attributes: dict[str, AttrValue] = msgspec.field(default_factory=dict)
    tags: tuple[str, ...] = ()
    raw_event: str = ""
    resource_attrs: dict[str, str] = msgspec.field(default_factory=dict)
