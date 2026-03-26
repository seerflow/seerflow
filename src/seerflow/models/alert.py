"""Alert, CorrelationRule, and SourceCondition data models.

Alert is produced by all detection engines (ML, Sigma, correlation, UEBA, IoC).
CorrelationRule defines YAML-loaded cross-source correlation rules.
SourceCondition defines per-source match conditions within a rule.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    from seerflow.detection.ensemble import DetectionResult
    from seerflow.models._types import AlertType, EntityType, FeedbackType
    from seerflow.models.event import SeerflowEvent, SeverityLevel


class SourceCondition(msgspec.Struct, frozen=True):
    """A condition matching events from a specific source in a correlation window.

    Note: ``frozen=True`` prevents field re-binding but does not deep-freeze
    the ``conditions`` dict. Consumers must treat it as read-only.
    Regex patterns in ``conditions`` values are validated by the YAML rule
    loader (S-040), not by this struct.
    """

    source_type: str  # e.g., "syslog", "otlp", "file"
    conditions: dict[str, str]  # field_name -> regex pattern
    min_count: int = 1  # minimum matching events required


class CorrelationRule(msgspec.Struct, frozen=True):
    """Declarative cross-source correlation rule loaded from YAML.

    Invariants (enforced by the YAML rule loader, S-040):
    - ``window_seconds > 0``
    - ``min_sources >= 1``
    - ``min_sources <= len(sources)``
    """

    name: str
    entity_type: EntityType
    window_seconds: int
    sources: tuple[SourceCondition, ...]
    min_sources: int
    alert_severity: SeverityLevel
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.min_sources < 1:
            raise ValueError("min_sources must be >= 1")
        if self.min_sources > len(self.sources):
            msg = (
                f"min_sources ({self.min_sources}) cannot exceed "
                f"number of sources ({len(self.sources)})"
            )
            raise ValueError(msg)


class Alert(msgspec.Struct, frozen=True):
    """Detection alert produced by any Seerflow detection engine.

    All five alert sources (ML ensemble, Sigma engine, correlation engine,
    UEBA scorer, threat intel matcher) produce this same struct.

    ``alert_id`` and ``entity_uuid`` are UUID5 strings (not ``uuid.UUID``)
    to match the string-based entity reference convention used throughout
    the pipeline (``SeerflowEvent.entity_refs: tuple[str, ...]``).

    ``feedback`` uses ``""`` (empty string) as the sentinel for "no feedback
    recorded yet". ``None`` is not used to keep the field non-optional for
    simpler serialization.
    """

    alert_id: str  # UUID5 string — matches entity_refs convention
    alert_type: AlertType
    timestamp_ns: int
    severity_id: SeverityLevel
    rule_name: str
    description: str
    entity_uuid: str  # UUID5 string — matches entity_refs convention
    entity_value: str
    entity_type: EntityType
    contributing_events: tuple[uuid.UUID, ...]
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    risk_score: float = 0.0
    dedup_key: str = ""
    dedup_count: int = 1
    feedback: FeedbackType = ""


def create_ml_alert(event: SeerflowEvent, result: DetectionResult) -> Alert:
    """Create an ML anomaly Alert from a SeerflowEvent and DetectionResult.

    Uses the first entity from ``event.entity_refs`` as the primary entity.
    If no entities are present, entity fields default to empty strings.
    """
    entity_refs = event.entity_refs
    return Alert(
        alert_id=str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"hst:{event.template_id}:{event.source_type}:{event.timestamp_ns}",
            )
        ),
        alert_type="ml",
        timestamp_ns=event.timestamp_ns,
        severity_id=event.severity_id,
        rule_name="hst-anomaly",
        description=(
            f"Anomaly detected: score={result.score:.3f} "
            f"threshold={result.upper_threshold:.3f} "
            f"direction={result.anomaly_direction}"
        ),
        entity_uuid=entity_refs[0] if entity_refs else "",
        entity_value=entity_refs[0] if entity_refs else "",
        entity_type="ip",
        contributing_events=(event.event_id,),
        risk_score=result.score,
        dedup_key=f"hst:{event.template_id}:{event.source_type}",
    )
