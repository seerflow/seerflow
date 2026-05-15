"""Pure-helper unit tests for the Postgres backend (S-073).

These tests do not require Docker or a live PostgreSQL — they exercise
the SQL builders, FTS sanitisation, and migration registry.
"""

from __future__ import annotations

from seerflow.models.query import AlertQuery, EventQuery, TimeRange
from seerflow.storage._postgres_alerts import _build_pg_alert_query
from seerflow.storage.postgres import _build_pg_query, _sanitize_pg_fts_query
from seerflow.storage.postgres_migrations import MIGRATIONS


class TestSanitizePgFtsQuery:
    def test_empty_returns_empty(self) -> None:
        assert _sanitize_pg_fts_query("") == ""

    def test_strips_quotes(self) -> None:
        assert _sanitize_pg_fts_query('hello "world"') == "hello world"
        assert _sanitize_pg_fts_query("''drop''") == "drop"

    def test_strips_whitespace(self) -> None:
        assert _sanitize_pg_fts_query("  ssh login  ") == "ssh login"

    def test_caps_at_256_chars(self) -> None:
        out = _sanitize_pg_fts_query("x" * 1000)
        assert len(out) == 256

    def test_strips_unprintable(self) -> None:
        assert _sanitize_pg_fts_query("admin\x00\x01login") == "adminlogin"


class TestBuildPgQuery:
    def test_no_filters_yields_true_where(self) -> None:
        where, joins, params, next_n = _build_pg_query(EventQuery())
        assert where == "TRUE"
        assert joins == ""
        assert params == []
        assert next_n == 1

    def test_time_range_filter(self) -> None:
        where, _, params, next_n = _build_pg_query(
            EventQuery(time_range=TimeRange(start_ns=100, end_ns=200))
        )
        assert "e.timestamp_ns >= $1" in where
        assert "e.timestamp_ns <= $2" in where
        assert params == [100, 200]
        assert next_n == 3

    def test_entity_uuid_adds_join(self) -> None:
        where, joins, params, _ = _build_pg_query(EventQuery(entity_uuid="abc"))
        assert "entity_events" in joins
        assert "ee.entity_uuid = $1" in where
        assert params == ["abc"]

    def test_text_query_uses_plainto_tsquery(self) -> None:
        where, _, params, _ = _build_pg_query(EventQuery(text_query="login failed"))
        assert "plainto_tsquery" in where
        assert params == ["login failed"]

    def test_empty_text_query_matches_nothing(self) -> None:
        where, _, params, _ = _build_pg_query(EventQuery(text_query="  "))
        assert "1=0" in where
        assert params == []

    def test_all_filters_combined(self) -> None:
        q = EventQuery(
            time_range=TimeRange(start_ns=1, end_ns=2),
            source_type="syslog",
            severity_min=4,
            template_id=7,
            entity_uuid="ent",
        )
        _where, joins, params, next_n = _build_pg_query(q)
        assert "entity_events" in joins
        # Five filter values: start, end, source_type, severity_min, template_id, entity_uuid
        assert params == [1, 2, "syslog", 4, 7, "ent"]
        assert next_n == 7


class TestBuildPgAlertQuery:
    def test_no_filters_yields_true(self) -> None:
        where, params, next_n = _build_pg_alert_query(AlertQuery())
        assert where == "TRUE"
        assert params == []
        assert next_n == 1

    def test_tactic_filter(self) -> None:
        where, params, _ = _build_pg_alert_query(AlertQuery(tactic="execution"))
        assert "at.tactic = $1" in where
        assert params == ["execution"]

    def test_subtechnique_exact_match(self) -> None:
        where, params, _ = _build_pg_alert_query(AlertQuery(technique="T1547.001"))
        assert "atq.technique = $1" in where
        assert params == ["T1547.001"]

    def test_parent_technique_range(self) -> None:
        where, params, next_n = _build_pg_alert_query(AlertQuery(technique="T1053"))
        # Equality + range bounds
        assert "atq.technique = $1" in where
        assert "$2" in where and "$3" in where
        assert params == ["T1053", "T1053.", "T1053/"]
        assert next_n == 4


class TestPostgresMigrations:
    def test_version_keys_are_sequential(self) -> None:
        keys = sorted(MIGRATIONS)
        assert keys == list(range(1, len(MIGRATIONS) + 1))

    def test_all_entries_are_callable(self) -> None:
        for fn in MIGRATIONS.values():
            assert callable(fn)
