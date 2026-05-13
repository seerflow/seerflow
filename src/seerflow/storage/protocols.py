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
    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.llm.rule_suggestion.aggregator import PatternFeedbackRow
    from seerflow.models._types import FeedbackType
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.feedback import FeedbackEvent, FeedbackOrigin
    from seerflow.models.query import AlertQuery, EntityRelation, EventQuery, Page, TimeRange
    from seerflow.storage.sqlite import TemplateInfo


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

    async def prune_templates(self, min_count: int) -> int:
        """Delete templates whose ``event_count`` is strictly less than
        ``min_count``. Returns the number of rows removed.

        ``min_count == 0`` is a no-op (no row can have negative count).
        Negative ``min_count`` raises ``ValueError`` — callers must
        validate before calling.
        """
        ...

    async def reset_templates(self) -> int:
        """Delete every row from the templates table.

        Returns the number of rows removed. Does NOT touch the in-memory
        Drain3 parse tree — callers wanting a hard reset should also
        delete the ``drain3:global`` row via ``ModelStore.delete_state``.
        """
        ...

    async def flush(self) -> None: ...


@runtime_checkable
class AlertStore(Protocol):  # pragma: no cover
    """Alert CRUD interface."""

    async def write_alert(
        self,
        alert: Alert,
        dedup_window_ns: int = 900_000_000_000,
    ) -> bool: ...

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...

    async def update_feedback(
        self,
        alert_id: str,
        feedback: FeedbackType,
        note: str = "",
        origin: FeedbackOrigin = "api",
    ) -> None:
        """Write feedback, note, and origin to the alert row and append an
        audit-log event. Silent no-op if the alert does not exist. The SQLite
        backend guarantees atomicity via ``BEGIN IMMEDIATE``.
        """
        ...

    async def get_alert_by_id(self, alert_id: str) -> Alert | None: ...

    async def count_alerts_bucketed(
        self,
        *,
        alert_type: str,
        rule_name: str,
        time_range: TimeRange,
        bucket_ns: int,
    ) -> list[tuple[int, int]]:
        """Return ``(bucket_start_ns, count)`` pairs grouped by floor-divided
        ``timestamp_ns / bucket_ns``. Buckets with zero matches are omitted —
        the caller is responsible for densifying the grid.
        """
        ...

    async def get_feedback_stats(self) -> dict[str, int]: ...

    async def append_feedback_event(
        self,
        alert_id: str,
        feedback: FeedbackType,
        note: str,
        origin: FeedbackOrigin,
        submitted_at_ns: int,
    ) -> None:
        """Append an immutable row to the feedback audit log."""
        ...

    async def list_feedback_events(
        self, alert_id: str, page: int = 1, limit: int = 50
    ) -> Page[FeedbackEvent]:
        """Return feedback audit-log entries newest-first, paginated."""
        ...

    async def aggregate_tp_feedback(
        self,
        *,
        min_tp: int,
        window_ns: int | None = None,
        now_ns: int | None = None,
        limit: int = 50_000,
    ) -> tuple[PatternFeedbackRow, ...]:
        """Aggregate TP feedback rows by ``(alert_type, rule_name, entity_type)``.

        Used by the rule-suggestion service (S-100, FR-066) to surface ML
        patterns that have accumulated ``tp_count >= min_tp`` distinct TP
        verdicts. Only the **latest** verdict per ``alert_id`` is counted,
        so a TP→FP→TP flip-flop registers as one TP, not two.

        Args:
            min_tp: Filter floor — patterns with fewer TPs are omitted.
            window_ns: If provided (non-``None``), consider only feedback
                events with ``submitted_at_ns >= now_ns - window_ns``.
                ``None`` (default) means all-time.
            now_ns: Reference clock for ``window_ns``. Backends fall back
                to their own wall-clock when ``None``.
            limit: Scan ceiling — the row count actually inspected by the
                SQL query, **not** the returned row count. Protects
                long-running deployments where the feedback log grows
                into the millions; the result is conservative
                (under-counted patterns), never wrong.

        Returns:
            Tuple of ``PatternFeedbackRow`` instances ordered
            ``tp_count DESC, most_recent_tp_ns DESC``.
        """
        ...

    async def count_by_severity(self) -> dict[str, int]:
        """Return alert counts grouped by severity name.

        Keys are lowercase SeverityLevel names (e.g. ``"informational"``,
        ``"warning"``, ``"critical"``). Missing severities are omitted,
        not returned as ``0``. Values that do not map to a known
        SeverityLevel are bucketed under ``"unknown"``.
        """
        ...


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

    async def delete_state(self, key: str) -> None:
        """Delete serialized model state for ``key`` if present.

        No-op when the key does not exist. Intended for one-shot
        migration GC (e.g. purging orphan rows after a sanitized-key
        collision on load). Failures surface as exceptions; callers may
        choose to treat cleanup failures as best-effort.
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

    def set_entity_graph(self, graph: EntityGraph) -> None: ...


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


@runtime_checkable
class StorageBackend(
    LogStore,
    AlertStore,
    ModelStore,
    EntityStore,
    Protocol,
):  # pragma: no cover
    """Composite storage backend Protocol.

    Intersects the per-domain stores (:class:`LogStore`, :class:`AlertStore`,
    :class:`ModelStore`, :class:`EntityStore`) and adds the
    ``write_edge`` / ``load_edges`` subset of :class:`GraphStore` that both
    concrete backends implement, plus the lifecycle and template-catalog
    methods CLI entry points and the pipeline need.

    :func:`seerflow.storage.connect_storage` returns this Protocol so
    callers stay backend-agnostic. Concrete backends
    (:class:`~seerflow.storage.sqlite.SqliteBackend` and
    :class:`~seerflow.storage.postgres.PostgresBackend`) satisfy it
    structurally — no explicit ``implements`` relationship is required.

    Consumers that only need one responsibility (e.g. a correlation engine
    that only reads timelines) should depend on the narrower per-domain
    Protocol, not this composite. The per-domain ``GraphStore`` methods
    ``get_neighbors`` / ``shortest_path`` / ``get_subgraph`` are delivered
    by :class:`~seerflow.graph.backends.GraphBackend` and are deliberately
    not part of this composite.
    """

    async def write_edge(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        timestamp_ns: int,
    ) -> None:
        """Upsert a directed edge between two entities. See ``GraphStore``."""
        ...

    async def load_edges(self) -> list[tuple[str, str, str, int, int, int]]:
        """Return every persisted edge as ``(src, dst, type, first, last, count)``."""
        ...

    async def close(self) -> None:
        """Flush pending writes and release backend resources (idempotent)."""
        ...

    async def write_templates(self, templates: list[TemplateInfo]) -> None:
        """Persist Drain3 template catalog entries."""
        ...

    async def get_templates(self, limit: int = 1000) -> list[TemplateInfo]:
        """Return the top ``limit`` templates ordered by ``event_count`` DESC."""
        ...
