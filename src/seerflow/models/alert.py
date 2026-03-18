"""Alert, CorrelationRule, and SourceCondition data models.

Alert is produced by all detection engines (ML, Sigma, correlation, UEBA, IoC).
CorrelationRule defines YAML-loaded cross-source correlation rules.
SourceCondition defines per-source match conditions within a rule.
"""

import uuid
from typing import Literal

import msgspec

from seerflow.models.event import SeverityLevel

# Type aliases for constrained string fields.
AlertType = Literal["ml", "sigma", "correlation", "ueba", "ioc"]
FeedbackType = Literal["", "tp", "fp"]


class SourceCondition(msgspec.Struct, frozen=True):
    """A condition matching events from a specific source in a correlation window."""

    source_type: str  # e.g., "syslog", "otlp", "file"
    conditions: dict[str, str]  # field_name -> regex pattern
    min_count: int = 1  # minimum matching events required


class CorrelationRule(msgspec.Struct, frozen=True):
    """Declarative cross-source correlation rule loaded from YAML."""

    name: str
    entity_type: str  # "user" | "ip" | "host"
    window_seconds: int
    sources: tuple[SourceCondition, ...]
    min_sources: int
    alert_severity: SeverityLevel
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    description: str = ""


class Alert(msgspec.Struct, frozen=True):
    """Detection alert produced by any Seerflow detection engine.

    All five alert sources (ML ensemble, Sigma engine, correlation engine,
    UEBA scorer, threat intel matcher) produce this same struct.
    """

    alert_id: str
    alert_type: AlertType
    timestamp_ns: int
    severity_id: SeverityLevel
    rule_name: str
    description: str
    entity_uuid: str
    entity_value: str
    entity_type: str
    contributing_events: tuple[uuid.UUID, ...]
    mitre_tactics: tuple[str, ...] = ()
    mitre_techniques: tuple[str, ...] = ()
    risk_score: float = 0.0
    dedup_key: str = ""
    dedup_count: int = 1
    feedback: FeedbackType = ""
