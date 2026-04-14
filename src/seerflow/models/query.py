"""Query and pagination types for the Seerflow storage layer.

These are plain dataclasses (not msgspec Structs) because they are ephemeral
request objects never serialized to storage or wire format.

Storage contract: ``text_query`` MUST be passed to the FTS engine via a
parameterised interface (e.g., ``plainto_tsquery``, match query body).
String interpolation into SQL or query DSL strings is forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from seerflow.models._types import AlertType

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Nanosecond time range for event/alert queries."""

    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        if self.start_ns > self.end_ns:
            msg = f"start_ns ({self.start_ns}) must be <= end_ns ({self.end_ns})"
            raise ValueError(msg)


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

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"page must be >= 1, got {self.page}")
        if not (1 <= self.limit <= 1000):
            raise ValueError(f"limit must be between 1 and 1000, got {self.limit}")


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertQuery:
    """Composable filter for alert queries. None fields are not applied.

    The ``limit`` upper bound of 10 000 exists to support internal scan
    operations (e.g. ``/api/v1/attack/coverage`` which replaces the prior
    10-page x 1 000-row loop with a single SQL query). Public API DoS
    concerns are handled by per-endpoint rate limiting, not by capping
    this internal query primitive.
    """

    time_range: TimeRange | None = None
    alert_type: AlertType | None = None
    severity_min: int | None = None
    entity_uuid: str | None = None
    tactic: str | None = None
    technique: str | None = None
    page: int = 1
    limit: int = 100

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"page must be >= 1, got {self.page}")
        if not (1 <= self.limit <= 10_000):
            raise ValueError(f"limit must be between 1 and 10000, got {self.limit}")


@dataclass(frozen=True, slots=True)
class Page(Generic[_T]):
    """Paginated result wrapper returned by storage queries."""

    items: tuple[_T, ...]
    total: int
    page: int
    limit: int

    @property
    def has_next(self) -> bool:
        """True if there are more pages after the current one."""
        return len(self.items) > 0 and (self.page - 1) * self.limit + len(self.items) < self.total


@dataclass(frozen=True, kw_only=True, slots=True)
class EntityRelation:
    """A relationship between two entities in the entity graph."""

    entity_uuid: str
    entity_type: str
    entity_value: str
    relation_type: str
