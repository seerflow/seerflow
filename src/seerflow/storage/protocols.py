"""Storage Protocol interfaces for the Seerflow pipeline.

Five Protocols define the storage contract. Backends (SQLite, PostgreSQL)
implement these Protocols. All methods are async. All Protocols are
``@runtime_checkable`` for startup validation.

v1 Protocols: LogStore, AlertStore, ModelStore, EntityStore, GraphStore.
CheckpointStore is deferred (see architecture Appendix D).

Note: Type annotations use ``TYPE_CHECKING`` guards for zero-cost imports.
``typing.get_type_hints()`` will fail at runtime on these Protocol classes;
use ``inspect.signature()`` instead if you need runtime introspection of
method signatures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from seerflow.models._types import FeedbackType
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import AlertQuery, EntityRelation, EventQuery, Page, TimeRange


@runtime_checkable
class LogStore(Protocol):  # pragma: no cover
    """Event persistence and query interface."""

    async def write_events(self, events: list[SeerflowEvent]) -> None: ...

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...

    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]:
        """Full-text search across stored events.

        Args:
            query: Search string. Backends should treat this as a plain-text
                substring or FTS match — no SQL/regex interpretation.
            limit: Maximum number of results to return. Must be >= 1.
                Backends should clamp to an internal ceiling (e.g. 10 000)
                to prevent unbounded result sets.
        """
        ...


@runtime_checkable
class AlertStore(Protocol):  # pragma: no cover
    """Alert CRUD interface."""

    async def write_alert(self, alert: Alert) -> None: ...

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...

    async def update_feedback(self, alert_id: str, feedback: FeedbackType) -> None: ...


@runtime_checkable
class ModelStore(Protocol):  # pragma: no cover
    """ML model state key-value persistence.

    Keys must be non-empty, ASCII-only, and <= 256 characters.
    Convention: ``<model_type>:<entity_or_scope>`` (e.g.
    ``"hst:host:web-01"``, ``"cusum:global"``).
    """

    async def save_state(self, key: str, data: bytes) -> None: ...

    async def load_state(self, key: str) -> bytes | None:
        """Load serialized model state.

        Returns:
            Raw bytes previously stored via ``save_state``, or ``None``
            if no state exists for the given key (first run or after a
            key rotation). Callers must handle ``None`` by initializing
            a fresh model.
        """
        ...


@runtime_checkable
class EntityStore(Protocol):  # pragma: no cover
    """Entity timeline and relationship queries."""

    async def get_timeline(
        self,
        entity_uuid: str,
        time_range: TimeRange,
        source_type: str | None = None,
        severity_min: int | None = None,
        limit: int = 10_000,
    ) -> list[SeerflowEvent]: ...

    async def get_related(self, entity_uuid: str) -> list[EntityRelation]: ...


@runtime_checkable
class GraphStore(Protocol):  # pragma: no cover
    """Entity relationship graph operations."""

    async def write_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None: ...

    async def load_edges(
        self,
    ) -> list[tuple[str, str, str, int, int, int]]: ...

    async def get_neighbors(
        self,
        entity_id: str,
        rel_types: tuple[str, ...] | None = None,
        depth: int = 1,
    ) -> list[dict[str, str]]: ...

    async def shortest_path(
        self,
        source_id: str,
        target_id: str,
    ) -> list[str]: ...

    async def get_subgraph(
        self,
        entity_id: str,
        depth: int = 2,
    ) -> tuple[list[str], list[dict[str, str]]]: ...
