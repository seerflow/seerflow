"""Tests for storage Protocol interfaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.storage import AlertStore, EntityStore, LogStore, ModelStore

if TYPE_CHECKING:
    from seerflow.models.alert import Alert, FeedbackType
    from seerflow.models.event import SeerflowEvent
    from seerflow.models.query import AlertQuery, EntityRelation, EventQuery, Page, TimeRange


class _MockLogStore:
    async def write_events(self, events: list[SeerflowEvent]) -> None: ...
    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]: ...
    async def search_text(self, query: str, limit: int) -> list[SeerflowEvent]: ...


class _MockAlertStore:
    async def write_alert(self, alert: Alert) -> None: ...
    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]: ...
    async def update_feedback(self, alert_id: str, feedback: FeedbackType) -> None: ...


class _MockModelStore:
    async def save_state(self, key: str, data: bytes) -> None: ...
    async def load_state(self, key: str) -> bytes | None: ...


class _MockEntityStore:
    async def get_timeline(
        self, entity_uuid: str, time_range: TimeRange
    ) -> list[SeerflowEvent]: ...
    async def get_related(self, entity_uuid: str) -> list[EntityRelation]: ...


class _NotAStore:
    """Class that does not conform to any storage Protocol."""

    async def do_nothing(self) -> None: ...


class TestLogStore:
    def test_runtime_checkable(self) -> None:
        assert isinstance(_MockLogStore(), LogStore)

    def test_non_conforming_fails(self) -> None:
        assert not isinstance(_NotAStore(), LogStore)


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


class TestImports:
    def test_protocols_importable_from_storage(self) -> None:
        from seerflow.storage import AlertStore, EntityStore, LogStore, ModelStore

        assert LogStore is not None
        assert AlertStore is not None
        assert ModelStore is not None
        assert EntityStore is not None
