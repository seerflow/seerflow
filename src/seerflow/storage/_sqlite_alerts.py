"""Alert-domain storage for the SQLite backend.

Internal split of ``seerflow.storage.sqlite`` per S-170 to keep that module
under the 800-line ceiling. Provides :class:`_SqliteAlertMixin`, which
composes into :class:`seerflow.storage.sqlite.SqliteBackend` and contributes
the alert persistence, query, feedback, and aggregation methods.

The mixin expects ``self._conn`` to be an ``aiosqlite.Connection`` managed
by the enclosing backend.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import msgspec

from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.query import Page
from seerflow.sigma.attack import format_technique

if TYPE_CHECKING:
    import aiosqlite

    from seerflow.models._types import FeedbackType
    from seerflow.models.query import AlertQuery

_log = logging.getLogger(__name__)


# See _migrate_v3_mitre_junctions in storage/migrations.py for the canonical schema.
def _build_alert_query(filters: AlertQuery) -> tuple[str, list[Any]]:
    """Build WHERE clause and params from AlertQuery (including mitre filters).

    When ``tactic`` or ``technique`` is set, the caller drives the query from
    the matching junction table (``alert_tactics at`` or ``alert_techniques
    atq``) so the composite ``(tactic|technique, timestamp_ns DESC)`` index
    satisfies both the predicate and the ORDER BY. When both are set, the
    driver is the tactic junction and technique becomes a correlated EXISTS.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if filters.time_range is not None:
        clauses.append("a.timestamp_ns >= ?")
        params.append(filters.time_range.start_ns)
        clauses.append("a.timestamp_ns <= ?")
        params.append(filters.time_range.end_ns)
    if filters.alert_type is not None:
        clauses.append("a.alert_type = ?")
        params.append(filters.alert_type)
    if filters.severity_min is not None:
        clauses.append("a.severity_id >= ?")
        params.append(filters.severity_min)
    if filters.entity_uuid is not None:
        clauses.append("a.entity_uuid = ?")
        params.append(filters.entity_uuid)
    if filters.tactic is not None:
        clauses.append("at.tactic = ?")
        params.append(filters.tactic)
    if filters.technique is not None:
        # If tactic is also set, the driver is alert_tactics so technique
        # becomes a correlated EXISTS on alert_techniques. Otherwise the
        # driver is alert_techniques and we filter directly on atq.technique.
        if filters.tactic is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM alert_techniques atq2 "
                "WHERE atq2.dedup_key = a.dedup_key AND atq2.technique = ?)"
            )
        else:
            clauses.append("atq.technique = ?")
        params.append(format_technique(filters.technique))
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


_INSERT_ALERT_SQL = """\
INSERT INTO alerts (
    alert_id, alert_type, timestamp_ns, severity_id, rule_name,
    entity_uuid, entity_type, entity_value, dedup_key, dedup_count,
    risk_score, feedback, data
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(dedup_key) DO UPDATE SET
    dedup_count = CASE
        WHEN ABS(excluded.timestamp_ns - alerts.timestamp_ns) <= ?
        THEN alerts.dedup_count + 1
        ELSE 1
    END,
    timestamp_ns = CASE
        WHEN ABS(excluded.timestamp_ns - alerts.timestamp_ns) <= ?
        THEN alerts.timestamp_ns
        ELSE excluded.timestamp_ns
    END,
    alert_id = excluded.alert_id,
    data = excluded.data
RETURNING dedup_count"""


class _SqliteAlertMixin:
    """Alert-domain methods. Requires ``self._conn`` (aiosqlite.Connection)."""

    __slots__ = ()

    _conn: aiosqlite.Connection

    async def write_alert(
        self,
        alert: Alert,
        dedup_window_ns: int = 900_000_000_000,
    ) -> bool:
        """Persist an alert with time-windowed dedup upsert on conflict.

        Within *dedup_window_ns* nanoseconds of the existing alert the
        ``dedup_count`` is incremented and the original ``timestamp_ns`` is
        preserved.  Outside the window the count resets to 1 and the
        timestamp is replaced.

        Returns:
            True if this was a new insert or a window-reset (dedup_count == 1),
            False if the alert was a dedup bump within the window
            (dedup_count > 1).
        """
        data = msgspec.msgpack.encode(alert)
        params = (
            alert.alert_id,
            alert.alert_type,
            alert.timestamp_ns,
            int(alert.severity_id),
            alert.rule_name,
            alert.entity_uuid,
            alert.entity_type,
            alert.entity_value,
            alert.dedup_key,
            alert.dedup_count,
            alert.risk_score,
            alert.feedback,
            data,
            dedup_window_ns,
            dedup_window_ns,
        )
        try:
            async with await self._conn.execute(_INSERT_ALERT_SQL, params) as cursor:
                row = await cursor.fetchone()
            # Only refresh junction rows when this is a fresh insert or a
            # window-reset (dedup_count == 1). Within-window dedup bumps
            # preserve the stored alert and its timestamp, so its junction
            # rows are already correct.
            if row is not None and row[0] == 1:
                await self._conn.execute(
                    "DELETE FROM alert_tactics WHERE dedup_key = ?", (alert.dedup_key,)
                )
                await self._conn.execute(
                    "DELETE FROM alert_techniques WHERE dedup_key = ?", (alert.dedup_key,)
                )
                if alert.mitre_tactics:
                    await self._conn.executemany(
                        "INSERT OR IGNORE INTO alert_tactics "
                        "(dedup_key, tactic, timestamp_ns) VALUES (?, ?, ?)",
                        [(alert.dedup_key, t, alert.timestamp_ns) for t in alert.mitre_tactics],
                    )
                if alert.mitre_techniques:
                    await self._conn.executemany(
                        "INSERT OR IGNORE INTO alert_techniques "
                        "(dedup_key, technique, timestamp_ns) VALUES (?, ?, ?)",
                        [
                            (alert.dedup_key, format_technique(t), alert.timestamp_ns)
                            for t in alert.mitre_techniques
                        ],
                    )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("write_alert failed for alert %s", alert.alert_id)
            raise
        return row is not None and row[0] == 1

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:
        """Query alerts with composable filters and pagination (all SQL-level).

        When a mitre filter (``tactic`` / ``technique``) is set, the query is
        driven from the matching junction table so the composite
        ``(tactic|technique, timestamp_ns DESC)`` index satisfies both the
        predicate and the ORDER BY without scanning the ``alerts`` table.
        """
        where, params = _build_alert_query(filters)

        if filters.tactic is not None:
            driver = "alert_tactics AS at JOIN alerts a ON a.dedup_key = at.dedup_key"
            order_col = "at.timestamp_ns"
        elif filters.technique is not None:
            driver = "alert_techniques AS atq JOIN alerts a ON a.dedup_key = atq.dedup_key"
            order_col = "atq.timestamp_ns"
        else:
            driver = "alerts a"
            order_col = "a.timestamp_ns"

        # driver, where, order_col are assembled from hardcoded SQL fragments;
        # user values are bound exclusively via params.
        count_sql = f"SELECT COUNT(*) FROM {driver} WHERE {where}"  # noqa: S608  # nosec B608
        async with await self._conn.execute(count_sql, params) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0

        offset = (filters.page - 1) * filters.limit
        data_sql = (
            f"SELECT a.data, a.dedup_count FROM {driver} WHERE {where} "  # noqa: S608  # nosec B608
            f"ORDER BY {order_col} DESC LIMIT ? OFFSET ?"
        )
        async with await self._conn.execute(data_sql, [*params, filters.limit, offset]) as cursor:
            rows = await cursor.fetchall()
        items = tuple(
            msgspec.structs.replace(
                msgspec.msgpack.decode(row[0], type=Alert),
                dedup_count=row[1],
            )
            for row in rows
        )
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def update_feedback(self, alert_id: str, feedback: FeedbackType, note: str = "") -> None:
        """Update alert feedback and re-encode the BLOB.

        Implementation note: this performs a SELECT then UPDATE. On the SQLite
        backend this is safe because a single aiosqlite connection serializes
        all operations. A PostgreSQL backend MUST use SELECT ... FOR UPDATE
        inside a transaction to prevent a concurrent write from being lost.
        """
        async with await self._conn.execute(
            "SELECT data FROM alerts WHERE alert_id = ?", [alert_id]
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return
        alert = msgspec.msgpack.decode(row[0], type=Alert)
        updated = msgspec.structs.replace(alert, feedback=feedback, feedback_note=note)
        data = msgspec.msgpack.encode(updated)
        try:
            await self._conn.execute(
                "UPDATE alerts SET feedback = ?, data = ? WHERE alert_id = ?",
                [feedback, data, alert_id],
            )
            await self._conn.commit()
        except Exception:
            await self._conn.rollback()
            _log.exception("update_feedback failed for alert %s", alert_id)
            raise

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        """Retrieve a single alert by ID, or None if not found."""
        async with await self._conn.execute(
            "SELECT data FROM alerts WHERE alert_id = ?", [alert_id]
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return msgspec.msgpack.decode(row[0], type=Alert)

    async def get_feedback_stats(self) -> dict[str, int]:
        """Return feedback counts: tp, fp, total."""
        async with await self._conn.execute(
            "SELECT feedback, COUNT(*) FROM alerts"
            " WHERE feedback IN ('tp', 'fp') GROUP BY feedback"
        ) as cursor:
            rows = await cursor.fetchall()
        stats: dict[str, int] = {"tp": 0, "fp": 0, "total": 0}
        for fb_type, count in rows:
            if fb_type in ("tp", "fp"):
                stats[fb_type] = count
                stats["total"] += count
        return stats

    async def count_by_severity(self) -> dict[str, int]:
        """Return alert counts grouped by severity name (lowercase).

        Invalid ``severity_id`` values (outside the ``SeverityLevel`` enum)
        are bucketed under ``"unknown"`` so dirty data cannot crash the
        stats endpoint.
        """
        async with await self._conn.execute(
            "SELECT severity_id, COUNT(*) FROM alerts GROUP BY severity_id"
        ) as cursor:
            rows = await cursor.fetchall()
        counts: dict[str, int] = {}
        for severity_id, count in rows:
            try:
                name = SeverityLevel(int(severity_id)).name.lower()
            except (ValueError, TypeError):
                # ValueError: severity_id outside enum range OR non-numeric text
                # TypeError: severity_id is None (SQLite type affinity edge case)
                name = "unknown"
            counts[name] = counts.get(name, 0) + int(count)
        return counts
