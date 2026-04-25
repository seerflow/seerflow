"""EXPLAIN QUERY PLAN check: parent-technique filter still uses the index."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


@pytest.mark.integration
class TestAttackFilterQueryPlan:
    async def test_parent_technique_uses_covering_index(self, backend: SqliteBackend) -> None:
        sql = (
            "SELECT a.data, a.dedup_count "
            "FROM alert_techniques AS atq JOIN alerts a "
            "ON a.dedup_key = atq.dedup_key "
            "WHERE (atq.technique = ? "
            "OR (atq.technique > ? AND atq.technique < ?)) "
            "ORDER BY atq.timestamp_ns DESC LIMIT 50 OFFSET 0"
        )
        params = ["T1053", "T1053.", "T1053/"]
        async with await backend._conn.execute(  # type: ignore[attr-defined]
            "EXPLAIN QUERY PLAN " + sql, params
        ) as cur:
            rows = await cur.fetchall()
        plan_text = "\n".join(str(row) for row in rows)
        # The index name is stable across SQLite versions; require it.
        assert "idx_alert_techniques_technique_time" in plan_text, plan_text
        # No full-table scan on the junction table (the wording "SCAN" with no
        # USING INDEX qualifier indicates a table scan in every SQLite version
        # we ship against).
        assert "SCAN alert_techniques" not in plan_text, plan_text
        # Note: SQLite >= 3.30 also emits "MULTI-INDEX OR" for the
        # OR-of-index-seeks plan; older SQLite uses different phrasing but
        # still drives both legs from the index (covered by the two checks
        # above). We do not assert on the version-specific phrasing.
