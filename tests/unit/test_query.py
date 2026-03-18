"""Tests for query types: TimeRange, EventQuery, AlertQuery, Page, EntityRelation."""

from __future__ import annotations

from seerflow.models.query import (
    AlertQuery,
    EntityRelation,
    EventQuery,
    Page,
    TimeRange,
)


class TestTimeRange:
    def test_create(self) -> None:
        tr = TimeRange(start_ns=1000, end_ns=2000)
        assert tr.start_ns == 1000
        assert tr.end_ns == 2000

    def test_frozen(self) -> None:
        import pytest

        tr = TimeRange(start_ns=1, end_ns=2)
        with pytest.raises(AttributeError):
            tr.start_ns = 99  # type: ignore[misc]


class TestEventQuery:
    def test_defaults(self) -> None:
        q = EventQuery()
        assert q.time_range is None
        assert q.source_type is None
        assert q.severity_min is None
        assert q.template_id is None
        assert q.entity_uuid is None
        assert q.text_query is None
        assert q.page == 1
        assert q.limit == 100

    def test_with_filters(self) -> None:
        tr = TimeRange(start_ns=1000, end_ns=2000)
        q = EventQuery(
            time_range=tr,
            source_type="syslog",
            severity_min=3,
            template_id=42,
            entity_uuid="uuid-1",
            text_query="error",
            page=2,
            limit=50,
        )
        assert q.time_range == tr
        assert q.source_type == "syslog"
        assert q.severity_min == 3
        assert q.template_id == 42
        assert q.entity_uuid == "uuid-1"
        assert q.text_query == "error"
        assert q.page == 2
        assert q.limit == 50


class TestAlertQuery:
    def test_defaults(self) -> None:
        q = AlertQuery()
        assert q.time_range is None
        assert q.alert_type is None
        assert q.severity_min is None
        assert q.entity_uuid is None
        assert q.page == 1
        assert q.limit == 100

    def test_with_filters(self) -> None:
        q = AlertQuery(
            alert_type="sigma",
            severity_min=4,
            entity_uuid="uuid-2",
            page=3,
            limit=25,
        )
        assert q.alert_type == "sigma"
        assert q.severity_min == 4
        assert q.page == 3


class TestPage:
    def test_creation(self) -> None:
        page: Page[str] = Page(
            items=["a", "b", "c"],
            total=50,
            page=1,
            limit=10,
        )
        assert page.items == ["a", "b", "c"]
        assert page.total == 50
        assert page.page == 1
        assert page.limit == 10

    def test_has_next_true(self) -> None:
        page: Page[int] = Page(items=[1, 2, 3], total=50, page=1, limit=10)
        assert page.has_next is True

    def test_has_next_false_last_page(self) -> None:
        page: Page[int] = Page(items=[1, 2], total=12, page=2, limit=10)
        assert page.has_next is False

    def test_has_next_false_underfull(self) -> None:
        page: Page[int] = Page(items=[1, 2, 3], total=3, page=1, limit=10)
        assert page.has_next is False

    def test_empty_page(self) -> None:
        page: Page[str] = Page(items=[], total=0, page=1, limit=10)
        assert page.has_next is False
        assert page.items == []


class TestEntityRelation:
    def test_create(self) -> None:
        rel = EntityRelation(
            entity_uuid="uuid-1",
            entity_type="ip",
            entity_value="192.168.1.1",
            relation_type="authenticated_from",
        )
        assert rel.entity_uuid == "uuid-1"
        assert rel.entity_type == "ip"
        assert rel.entity_value == "192.168.1.1"
        assert rel.relation_type == "authenticated_from"
