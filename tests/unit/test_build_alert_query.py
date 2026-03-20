"""Direct unit tests for _build_alert_query."""

from __future__ import annotations

from seerflow.models.query import AlertQuery, TimeRange
from seerflow.storage.sqlite import _build_alert_query


class TestBuildAlertQuery:
    def test_no_filters(self) -> None:
        where, params = _build_alert_query(AlertQuery())
        assert where == "1=1"
        assert params == []

    def test_time_range(self) -> None:
        tr = TimeRange(start_ns=100, end_ns=200)
        where, params = _build_alert_query(AlertQuery(time_range=tr))
        assert "a.timestamp_ns >= ?" in where
        assert "a.timestamp_ns <= ?" in where
        assert params == [100, 200]

    def test_alert_type(self) -> None:
        where, params = _build_alert_query(AlertQuery(alert_type="sigma"))
        assert "a.alert_type = ?" in where
        assert params == ["sigma"]

    def test_severity_min(self) -> None:
        where, params = _build_alert_query(AlertQuery(severity_min=3))
        assert "a.severity_id >= ?" in where
        assert params == [3]

    def test_entity_uuid(self) -> None:
        where, params = _build_alert_query(AlertQuery(entity_uuid="uuid-123"))
        assert "a.entity_uuid = ?" in where
        assert params == ["uuid-123"]

    def test_compound_filters(self) -> None:
        tr = TimeRange(start_ns=100, end_ns=200)
        where, params = _build_alert_query(
            AlertQuery(time_range=tr, alert_type="ml", severity_min=4, entity_uuid="uuid-abc")
        )
        assert " AND " in where
        assert len(params) == 5  # start, end, type, severity, entity
