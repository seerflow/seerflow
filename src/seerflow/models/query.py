"""Query and pagination types for the Seerflow storage layer.

These are plain dataclasses (not msgspec Structs) because they are ephemeral
request objects never serialized to storage or wire format.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Nanosecond time range for event/alert queries."""

    start_ns: int
    end_ns: int


@dataclass(frozen=True, kw_only=True, slots=True)
class EventQuery:
    """Composable filter for event queries. None fields are not applied."""

    time_range: TimeRange | None = None
    source_type: str | None = None
    severity_min: int | None = None
    template_id: int | None = None
    entity_uuid: str | None = None
    text_query: str | None = None
    page: int = 1
    limit: int = 100


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertQuery:
    """Composable filter for alert queries. None fields are not applied."""

    time_range: TimeRange | None = None
    alert_type: str | None = None
    severity_min: int | None = None
    entity_uuid: str | None = None
    page: int = 1
    limit: int = 100


@dataclass(frozen=True, slots=True)
class Page[T]:
    """Paginated result wrapper returned by storage queries."""

    items: list[T]
    total: int
    page: int
    limit: int

    @property
    def has_next(self) -> bool:
        """True if there are more pages after the current one."""
        return self.page * self.limit < self.total


@dataclass(frozen=True, slots=True)
class EntityRelation:
    """A relationship between two entities in the entity graph."""

    entity_uuid: str
    entity_type: str
    entity_value: str
    relation_type: str
