"""Lightweight Alert builder for router unit tests.

Keeps every field optional so each test can override only what the rule
predicate cares about.
"""

from __future__ import annotations

import uuid

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def make_alert(
    *,
    alert_type: str = "sigma",
    rule_name: str = "default-rule",
    severity_id: SeverityLevel = SeverityLevel.WARNING,
    entity_type: str = "user",
    entity_uuid: str | None = None,
    timestamp_ns: int = 1_700_000_000_000_000_000,
    alert_id: str | None = None,
    dedup_key: str = "dk",
    dedup_count: int = 1,
) -> Alert:
    return Alert(
        alert_id=alert_id or str(uuid.uuid5(uuid.NAMESPACE_OID, rule_name + str(timestamp_ns))),
        alert_type=alert_type,
        rule_name=rule_name,
        severity_id=severity_id,
        entity_type=entity_type,
        entity_uuid=entity_uuid or str(uuid.uuid5(uuid.NAMESPACE_OID, "ent-" + rule_name)),
        timestamp_ns=timestamp_ns,
        dedup_key=dedup_key,
        dedup_count=dedup_count,
        description="",
        entity_value="",
        contributing_events=(),
    )
