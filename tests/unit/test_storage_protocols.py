# mypy: disable-error-code="empty-body"
"""Tests for storage Protocol interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

import seerflow.storage as storage_mod
from seerflow.storage import AlertStore, EntityStore, GraphStore, LogStore, ModelStore

if TYPE_CHECKING:
    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.models._types import FeedbackType
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import AlertQuery, EntityRelation, EventQuery, Page, TimeRange


# -- Mock implementations (inherit from Protocol to satisfy mypy) -----------


class _MockLogStore(LogStore):
    async def write_events(self, events: list[SeerflowEvent]) -> None: ...
    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...
    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]: ...
    async def flush(self) -> None: ...


class _MockAlertStore(AlertStore):
    async def write_alert(self, alert: Alert, dedup_window_ns: int = 900_000_000_000) -> bool: ...
    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...
    async def update_feedback(self, alert_id: str, feedback: FeedbackType) -> None: ...


class _MockModelStore(ModelStore):
    async def save_state(self, key: str, data: bytes) -> None: ...
    async def load_state(self, key: str) -> bytes | None: ...


class _MockEntityStore(EntityStore):
    async def get_timeline(
        self, entity_uuid: str, time_range: TimeRange
    ) -> list[SeerflowEvent]: ...
    async def get_related(self, entity_uuid: str) -> list[EntityRelation]: ...
    def set_entity_graph(self, graph: EntityGraph) -> None: ...


class _MockGraphStore(GraphStore):
    async def write_edge(
        self, source_id: str, target_id: str, rel_type: str, timestamp_ns: int
    ) -> None: ...
    async def load_edges(self) -> list[tuple[str, str, str, int, int, int]]:
        return []

    async def get_neighbors(
        self, entity_id: str, rel_types: tuple[str, ...] | None = None, depth: int = 1
    ) -> list[dict[str, str]]: ...
    async def shortest_path(self, source_id: str, target_id: str) -> list[str]: ...
    async def get_subgraph(
        self, entity_id: str, depth: int = 2
    ) -> tuple[list[str], list[dict[str, str]]]: ...


# -- Non-conforming helpers -------------------------------------------------


class _NotAStore:
    """Class that does not conform to any storage Protocol."""

    async def do_nothing(self) -> None: ...


class _PartialLogStore:
    """Has ``write_events`` but missing ``query_events`` and ``search_text``."""

    async def write_events(self, events: list[SeerflowEvent]) -> None: ...


class _SyncLogStore:
    """Synchronous imposter — has the right method names but sync signatures.

    ``@runtime_checkable`` only checks attribute existence, not whether methods
    are coroutines. This class passes ``isinstance(_, LogStore)`` despite being
    synchronous — a documented limitation of runtime Protocol checks. Backend
    validation at startup should use ``inspect.iscoroutinefunction`` for async
    enforcement.
    """

    def write_events(self, events: list[SeerflowEvent]) -> None: ...
    def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...
    def search_text(self, query: str, limit: int) -> list[SeerflowEvent]: ...
    def flush(self) -> None: ...


# -- Tests ------------------------------------------------------------------


class TestLogStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockLogStore(), LogStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), LogStore)

    def test_partial_implementation_fails(self) -> None:
        """A class missing required methods must not satisfy the Protocol."""
        assert not isinstance(_PartialLogStore(), LogStore)

    def test_sync_imposter_passes_isinstance(self) -> None:
        """Document that runtime_checkable does NOT verify async signatures.

        ``isinstance`` only checks that the method names exist — it does not
        inspect whether they are coroutines. Backend validation at startup
        should use ``inspect.iscoroutinefunction`` for async enforcement.
        """
        assert isinstance(_SyncLogStore(), LogStore)


class TestAlertStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockAlertStore(), AlertStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), AlertStore)


class TestModelStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockModelStore(), ModelStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), ModelStore)


class TestEntityStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockEntityStore(), EntityStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), EntityStore)


class TestGraphStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockGraphStore(), GraphStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), GraphStore)


class TestExports:
    def test_all_protocols_in_dunder_all(self) -> None:
        """Every Protocol must be listed in ``storage.__all__``."""
        expected = {
            "AlertStore",
            "EntityStore",
            "GraphStore",
            "LogStore",
            "ModelStore",
            "SqliteBackend",
        }
        assert expected == set(storage_mod.__all__)


class TestTypeCheckingGuard:
    def test_get_type_hints_fails_at_runtime(self) -> None:
        """``get_type_hints()`` cannot resolve TYPE_CHECKING-guarded imports.

        Protocol type annotations reference models behind ``if TYPE_CHECKING``,
        so ``typing.get_type_hints()`` raises ``NameError`` at runtime.
        Use ``inspect.signature()`` instead for runtime introspection.
        """
        import typing

        import pytest

        with pytest.raises(NameError):
            typing.get_type_hints(LogStore.write_events)
