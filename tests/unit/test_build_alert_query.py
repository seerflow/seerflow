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


def test_build_alert_query_emits_tactic_predicate():
    """Tactic filter emits a direct predicate; junction is the query driver."""
    q = AlertQuery(
        time_range=TimeRange(start_ns=0, end_ns=1),
        tactic="discovery",
    )
    where, params = _build_alert_query(q)
    assert "at.tactic = ?" in where
    assert "discovery" in params


def test_build_alert_query_emits_technique_predicate_normalized():
    """Technique filter emits a direct predicate and normalizes the value."""
    q = AlertQuery(
        time_range=TimeRange(start_ns=0, end_ns=1),
        technique="t1059.001",
    )
    where, params = _build_alert_query(q)
    assert "atq.technique = ?" in where
    assert "T1059.001" in params


def test_build_alert_query_tactic_and_technique_uses_exists_for_technique():
    """When both are set, tactic drives and technique becomes a correlated EXISTS."""
    q = AlertQuery(tactic="discovery", technique="t1059.001")
    where, params = _build_alert_query(q)
    assert "at.tactic = ?" in where
    assert "EXISTS" in where
    assert "alert_techniques" in where
    assert "discovery" in params
    assert "T1059.001" in params
