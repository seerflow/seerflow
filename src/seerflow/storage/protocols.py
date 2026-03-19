"""Storage Protocol interfaces for the Seerflow pipeline.

Four Protocols define the storage contract. Backends (SQLite, PostgreSQL)
implement these Protocols. All methods are async. All Protocols are
``@runtime_checkable`` for startup validation.

v1 Protocols: LogStore, AlertStore, ModelStore, EntityStore.
GraphStore and CheckpointStore are deferred (see architecture Appendix D).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from seerflow.models.alert import Alert, FeedbackType
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import AlertQuery, EntityRelation, EventQuery, Page, TimeRange


@runtime_checkable
class LogStore(Protocol):
    """Event persistence and query interface."""

    async def write_events(self, events: list[SeerflowEvent]) -> None: ...

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]: ...


@runtime_checkable
class AlertStore(Protocol):
    """Alert CRUD interface."""

    async def write_alert(self, alert: Alert) -> None: ...

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...

    async def update_feedback(self, alert_id: str, feedback: FeedbackType) -> None: ...


@runtime_checkable
class ModelStore(Protocol):
    """ML model state key-value persistence."""

    async def save_state(self, key: str, data: bytes) -> None: ...

    async def load_state(self, key: str) -> bytes | None: ...


@runtime_checkable
class EntityStore(Protocol):
    """Entity timeline and relationship queries."""

    async def get_timeline(
        self, entity_uuid: str, time_range: TimeRange
    ) -> list[SeerflowEvent]: ...

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]: ...
