"""Shared test helpers for Seerflow tests."""

from __future__ import annotations

import time
import uuid

from seerflow.models.event import SeerflowEvent, SeverityLevel


def make_event(
    *,
    message: str = "test event",
    severity: SeverityLevel = SeverityLevel.INFORMATIONAL,
    entity_refs: tuple[str, ...] = (),
    source_type: str = "test",
    source_id: str = "test",
    log_source_category: str = "",
    log_source_product: str = "",
    log_source_service: str = "",
    related_ips: tuple[str, ...] = (),
    related_users: tuple[str, ...] = (),
    related_hosts: tuple[str, ...] = (),
    related_hashes: tuple[str, ...] = (),
    related_domains: tuple[str, ...] = (),
    related_files: tuple[str, ...] = (),
    related_processes: tuple[str, ...] = (),
    template_id: int = -1,
    template_str: str = "",
    event_id: uuid.UUID | None = None,
    timestamp_ns: int | None = None,
    event_kind: str = "event",
    event_category: str = "",
    event_type: str = "",
    event_action: str = "",
    event_outcome: str = "",
) -> SeerflowEvent:
    """Create a minimal SeerflowEvent with sensible defaults for testing."""
    now_ns = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=event_id if event_id is not None else uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=severity,
        message=message,
        source_type=source_type,
        source_id=source_id,
        log_source_category=log_source_category,
        log_source_product=log_source_product,
        log_source_service=log_source_service,
        entity_refs=entity_refs,
        related_ips=related_ips,
        related_users=related_users,
        related_hosts=related_hosts,
        related_hashes=related_hashes,
        related_domains=related_domains,
        related_files=related_files,
        related_processes=related_processes,
        template_id=template_id,
        template_str=template_str,
        event_kind=event_kind,
        event_category=event_category,
        event_type=event_type,
        event_action=event_action,
        event_outcome=event_outcome,
    )
