"""Alert-domain storage for the PostgreSQL backend (S-073).

Mirror of :mod:`seerflow.storage._sqlite_alerts` — same Protocol surface,
``$N`` placeholders, and PostgreSQL-flavoured ``ON CONFLICT`` / ``LEAST``
/ ``GREATEST`` constructs.

The mixin expects ``self._pool`` to be an :class:`asyncpg.Pool` managed
by the enclosing backend.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import msgspec

from seerflow.llm.rule_suggestion.aggregator import PatternFeedbackRow
from seerflow.llm.rule_suggestion.pattern_keys import derive_pattern_key
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel
from seerflow.models.feedback import FeedbackEvent
from seerflow.models.query import Page
from seerflow.sigma.attack import format_technique

if TYPE_CHECKING:
    import asyncpg

    from seerflow.models._types import FeedbackType
    from seerflow.models.feedback import FeedbackOrigin
    from seerflow.models.query import AlertQuery, TimeRange

_log = logging.getLogger(__name__)

# Mirror of ``_sqlite_alerts._AGG_MAX_CONTRIB_IDS`` — declared locally so the
# postgres backend never imports from a sibling backend module.
_AGG_MAX_CONTRIB_IDS = 16

# Mirror of ``_sqlite_alerts._GROUP_BY_COLUMNS`` — declared locally for the
# same no-sibling-import reason. The SQL column is resolved through this
# map's *values* (literal strings defined in-repo), never from caller
# input — keep in sync with the SQLite copy.
_GROUP_BY_COLUMNS: dict[str, str] = {"rule_name": "rule_name"}


def _build_pg_alert_query(filters: AlertQuery, start_param: int = 1) -> tuple[str, list[Any], int]:
    """Build WHERE + params for a PostgreSQL alert query.

    Mirrors :func:`seerflow.storage._sqlite_alerts._build_alert_query`,
    emitting asyncpg ``$N`` placeholders. ``start_param`` lets the caller
    reserve placeholder slots for trailing LIMIT/OFFSET bindings.
    """
    clauses: list[str] = []
    params: list[Any] = []
    n = start_param

    def add(clause_tmpl: str, value: Any) -> None:
        nonlocal n
        clauses.append(clause_tmpl.format(n=n))
        params.append(value)
        n += 1

    if filters.time_range is not None:
        add("a.timestamp_ns >= ${n}", filters.time_range.start_ns)
        add("a.timestamp_ns <= ${n}", filters.time_range.end_ns)
    if filters.alert_type is not None:
        add("a.alert_type = ${n}", filters.alert_type)
    if filters.severity_min is not None:
        add("a.severity_id >= ${n}", filters.severity_min)
    if filters.entity_uuid is not None:
        add("a.entity_uuid = ${n}", filters.entity_uuid)
    if filters.tactic is not None:
        add("at.tactic = ${n}", filters.tactic)
    if filters.technique is not None:
        technique = format_technique(filters.technique)
        if "." in technique:
            # Sub-technique exact match. The clause is assembled from
            # hardcoded SQL fragments; ``$n`` is a placeholder, not a value.
            if filters.tactic is not None:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM alert_techniques atq2 "  # noqa: S608  # nosec B608
                    f"WHERE atq2.dedup_key = a.dedup_key AND atq2.technique = ${n})"
                )
            else:
                clauses.append(f"atq.technique = ${n}")
            params.append(technique)
            n += 1
        else:
            lo = f"{technique}."
            hi = f"{technique}/"
            if filters.tactic is not None:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM alert_techniques atq2 "  # noqa: S608  # nosec B608
                    f"WHERE atq2.dedup_key = a.dedup_key "
                    f"AND (atq2.technique = ${n} "
                    f"OR (atq2.technique > ${n + 1} AND atq2.technique < ${n + 2})))"
                )
            else:
                clauses.append(
                    f"(atq.technique = ${n} "
                    f"OR (atq.technique > ${n + 1} AND atq.technique < ${n + 2}))"
                )
            params.extend([technique, lo, hi])
            n += 3

    where = " AND ".join(clauses) if clauses else "TRUE"
    return where, params, n


_INSERT_ALERT_SQL = """
INSERT INTO alerts (
    alert_id, alert_type, timestamp_ns, severity_id, rule_name,
    entity_uuid, entity_type, entity_value, dedup_key, dedup_count,
    risk_score, feedback, data
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (dedup_key) DO UPDATE SET
    dedup_count = CASE
        WHEN ABS(EXCLUDED.timestamp_ns - alerts.timestamp_ns) <= $14
        THEN alerts.dedup_count + 1
        ELSE 1
    END,
    timestamp_ns = CASE
        WHEN ABS(EXCLUDED.timestamp_ns - alerts.timestamp_ns) <= $14
        THEN alerts.timestamp_ns
        ELSE EXCLUDED.timestamp_ns
    END,
    alert_id = EXCLUDED.alert_id,
    data = EXCLUDED.data
RETURNING dedup_count
"""


class _PostgresAlertMixin:
    """Alert-domain methods. Requires ``self._pool`` (asyncpg.Pool)."""

    __slots__ = ()

    _pool: asyncpg.Pool

    async def write_alert(
        self,
        alert: Alert,
        dedup_window_ns: int = 900_000_000_000,
    ) -> bool:
        """Persist an alert with time-windowed dedup upsert on conflict.

        Returns:
            True if this was a new insert or a window-reset (dedup_count == 1),
            False on a dedup bump within the window (dedup_count > 1).
        """
        data = msgspec.msgpack.encode(alert)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                _INSERT_ALERT_SQL,
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
            )
            dedup_count = int(row["dedup_count"]) if row is not None else 0
            if dedup_count == 1:
                await conn.execute(
                    "DELETE FROM alert_tactics WHERE dedup_key = $1", alert.dedup_key
                )
                await conn.execute(
                    "DELETE FROM alert_techniques WHERE dedup_key = $1", alert.dedup_key
                )
                if alert.mitre_tactics:
                    await conn.executemany(
                        "INSERT INTO alert_tactics (dedup_key, tactic, timestamp_ns) "
                        "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        [(alert.dedup_key, t, alert.timestamp_ns) for t in alert.mitre_tactics],
                    )
                if alert.mitre_techniques:
                    await conn.executemany(
                        "INSERT INTO alert_techniques (dedup_key, technique, timestamp_ns) "
                        "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        [
                            (alert.dedup_key, format_technique(t), alert.timestamp_ns)
                            for t in alert.mitre_techniques
                        ],
                    )
        return dedup_count == 1

    async def query_alerts(self, filters: AlertQuery) -> Page[Alert]:
        """Query alerts with composable filters and pagination (SQL-level)."""
        where, params, next_n = _build_pg_alert_query(filters, start_param=1)

        if filters.tactic is not None:
            driver = "alert_tactics AS at JOIN alerts a ON a.dedup_key = at.dedup_key"
            order_col = "at.timestamp_ns"
        elif filters.technique is not None:
            driver = "alert_techniques AS atq JOIN alerts a ON a.dedup_key = atq.dedup_key"
            order_col = "atq.timestamp_ns"
        else:
            driver = "alerts a"
            order_col = "a.timestamp_ns"

        needs_dedup = (
            filters.tactic is None
            and filters.technique is not None
            and "." not in format_technique(filters.technique)
        )
        count_select = "COUNT(DISTINCT a.dedup_key)" if needs_dedup else "COUNT(*)"
        count_sql = f"SELECT {count_select} FROM {driver} WHERE {where}"  # noqa: S608  # nosec B608

        offset = (filters.page - 1) * filters.limit
        if needs_dedup:
            data_sql = (
                f"SELECT a.data, a.dedup_count FROM {driver} "  # noqa: S608  # nosec B608
                f"WHERE {where} GROUP BY a.dedup_key, a.data, a.dedup_count "
                f"ORDER BY MAX({order_col}) DESC LIMIT ${next_n} OFFSET ${next_n + 1}"
            )
        else:
            data_sql = (
                f"SELECT a.data, a.dedup_count FROM {driver} "  # noqa: S608  # nosec B608
                f"WHERE {where} ORDER BY {order_col} DESC "
                f"LIMIT ${next_n} OFFSET ${next_n + 1}"
            )

        async with self._pool.acquire() as conn:
            count_row = await conn.fetchrow(count_sql, *params)
            total = int(count_row[0]) if count_row else 0
            rows = await conn.fetch(data_sql, *params, filters.limit, offset)

        items = tuple(
            msgspec.structs.replace(
                msgspec.msgpack.decode(row["data"], type=Alert),
                dedup_count=int(row["dedup_count"]),
            )
            for row in rows
        )
        return Page(items=items, total=total, page=filters.page, limit=filters.limit)

    async def update_feedback(
        self,
        alert_id: str,
        feedback: FeedbackType,
        note: str = "",
        origin: FeedbackOrigin = "api",
    ) -> None:
        """Update alert feedback and append an audit-log row.

        Postgres uses ``SELECT ... FOR UPDATE`` inside the transaction so
        concurrent feedback updates serialise correctly (the SQLite backend
        relies on its single-connection write serialisation).
        """
        submitted_at_ns = time.time_ns()
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT data FROM alerts WHERE alert_id = $1 FOR UPDATE", alert_id
            )
            if row is None:
                return
            alert = msgspec.msgpack.decode(row["data"], type=Alert)
            updated = msgspec.structs.replace(alert, feedback=feedback, feedback_note=note)
            data = msgspec.msgpack.encode(updated)
            await conn.execute(
                "UPDATE alerts SET feedback = $1, data = $2 WHERE alert_id = $3",
                feedback,
                data,
                alert_id,
            )
            await conn.execute(
                "INSERT INTO alert_feedback_events "
                "(alert_id, feedback, note, origin, submitted_at_ns) "
                "VALUES ($1, $2, $3, $4, $5)",
                alert_id,
                feedback,
                note,
                origin,
                submitted_at_ns,
            )

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        """Retrieve a single alert by ID, or None if not found."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM alerts WHERE alert_id = $1", alert_id)
        if row is None:
            return None
        return msgspec.msgpack.decode(row["data"], type=Alert)

    async def count_alerts_bucketed(
        self,
        *,
        alert_type: str,
        rule_name: str,
        time_range: TimeRange,
        bucket_ns: int,
    ) -> list[tuple[int, int]]:
        """See :class:`AlertStore.count_alerts_bucketed` Protocol for the contract."""
        if bucket_ns <= 0:
            raise ValueError(f"bucket_ns must be positive, got {bucket_ns}")
        sql = (
            "SELECT (timestamp_ns / $1) * $2 AS bucket, COUNT(*) "
            "FROM alerts "
            "WHERE alert_type = $3 "
            "  AND rule_name = $4 "
            "  AND timestamp_ns >= $5 "
            "  AND timestamp_ns <  $6 "
            "GROUP BY bucket ORDER BY bucket"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                sql,
                bucket_ns,
                bucket_ns,
                alert_type,
                rule_name,
                time_range.start_ns,
                time_range.end_ns,
            )
        return [(int(r["bucket"]), int(r["count"])) for r in rows]

    async def count_alerts_grouped(
        self,
        *,
        alert_type: str,
        time_range: TimeRange,
        group_by: str,
    ) -> dict[str, int]:
        """See :class:`AlertStore.count_alerts_grouped` Protocol for the contract."""
        column = _GROUP_BY_COLUMNS.get(group_by)
        if column is None:
            raise ValueError(f"unsupported group_by: {group_by!r}")
        sql = (
            f"SELECT {column} AS grp, COUNT(*) "  # noqa: S608  # nosec B608
            "FROM alerts "
            "WHERE alert_type = $1 "
            "  AND timestamp_ns >= $2 "
            "  AND timestamp_ns <  $3 "
            f"GROUP BY {column}"  # nosec B608
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, alert_type, time_range.start_ns, time_range.end_ns)
        return {str(r["grp"]): int(r["count"]) for r in rows}

    async def get_feedback_stats(self) -> dict[str, int]:
        """Return feedback counts: tp, fp, total."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT feedback, COUNT(*) FROM alerts "
                "WHERE feedback IN ('tp', 'fp') GROUP BY feedback"
            )
        stats: dict[str, int] = {"tp": 0, "fp": 0, "total": 0}
        for row in rows:
            fb_type = row[0]
            count = int(row[1])
            if fb_type in ("tp", "fp"):
                stats[fb_type] = count
                stats["total"] += count
        return stats

    async def append_feedback_event(
        self,
        alert_id: str,
        feedback: FeedbackType,
        note: str,
        origin: FeedbackOrigin,
        submitted_at_ns: int,
    ) -> None:
        """Append an immutable row to the feedback audit log."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO alert_feedback_events "
                "(alert_id, feedback, note, origin, submitted_at_ns) "
                "VALUES ($1, $2, $3, $4, $5)",
                alert_id,
                feedback,
                note,
                origin,
                submitted_at_ns,
            )

    async def list_feedback_events(
        self, alert_id: str, page: int = 1, limit: int = 50
    ) -> Page[FeedbackEvent]:
        """Return feedback audit-log entries newest-first, paginated."""
        limit = max(1, min(limit, 200))
        page = max(1, page)
        offset = (page - 1) * limit

        async with self._pool.acquire() as conn:
            count_row = await conn.fetchrow(
                "SELECT COUNT(*) FROM alert_feedback_events WHERE alert_id = $1",
                alert_id,
            )
            total = int(count_row[0]) if count_row else 0
            rows = await conn.fetch(
                "SELECT id, feedback, note, origin, submitted_at_ns "
                "FROM alert_feedback_events WHERE alert_id = $1 "
                "ORDER BY submitted_at_ns DESC, id DESC LIMIT $2 OFFSET $3",
                alert_id,
                limit,
                offset,
            )

        items = tuple(
            FeedbackEvent(
                alert_id=alert_id,
                feedback=row["feedback"],
                note=row["note"],
                origin=row["origin"],
                submitted_at_ns=int(row["submitted_at_ns"]),
                id=int(row["id"]),
            )
            for row in rows
        )
        return Page(items=items, total=total, page=page, limit=limit)

    async def aggregate_tp_feedback(
        self,
        *,
        min_tp: int,
        window_ns: int | None = None,
        now_ns: int | None = None,
        limit: int = 50_000,
    ) -> tuple[PatternFeedbackRow, ...]:
        """Aggregate TP feedback by ``(alert_type, rule_name, entity_type)``.

        PostgreSQL mirror of :py:meth:`_SqliteAlertMixin.aggregate_tp_feedback`.
        Uses ``DISTINCT ON`` to pick the newest feedback row per alert id
        (PostgreSQL's idiomatic dedup pattern) and ``array_agg(... ORDER BY
        most_recent_per_alert DESC)`` to assemble the per-pattern ID list.
        """
        if window_ns is not None and window_ns > 0:
            reference_ns = now_ns if now_ns is not None else time.time_ns()
            window_floor_ns: int | None = reference_ns - window_ns
        else:
            window_floor_ns = None

        sql = """
            WITH latest_per_alert AS (
                SELECT DISTINCT ON (alert_id)
                    alert_id,
                    feedback,
                    submitted_at_ns AS most_recent_per_alert
                FROM alert_feedback_events
                WHERE ($1::BIGINT IS NULL OR submitted_at_ns >= $1::BIGINT)
                ORDER BY alert_id, submitted_at_ns DESC
            ),
            tp_alerts AS (
                SELECT
                    l.alert_id,
                    l.most_recent_per_alert,
                    a.alert_type,
                    a.rule_name,
                    a.entity_type
                FROM latest_per_alert l
                JOIN alerts a ON a.alert_id = l.alert_id
                WHERE l.feedback = 'tp'
            )
            SELECT
                alert_type,
                rule_name,
                entity_type,
                COUNT(*) AS tp_count,
                MAX(most_recent_per_alert) AS most_recent_tp_ns,
                array_agg(alert_id ORDER BY most_recent_per_alert DESC)::text[]
                    AS alert_ids
            FROM tp_alerts
            GROUP BY alert_type, rule_name, entity_type
            HAVING COUNT(*) >= $2::BIGINT
            ORDER BY tp_count DESC, most_recent_tp_ns DESC
            LIMIT $3::BIGINT
        """  # parameters bound, not interpolated
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                sql,
                window_floor_ns,
                int(min_tp),
                int(limit),
            )

        out: list[PatternFeedbackRow] = []
        for row in rows:
            key_alert = Alert(
                alert_id="",
                alert_type=row["alert_type"],
                timestamp_ns=0,
                severity_id=SeverityLevel.INFORMATIONAL,
                rule_name=row["rule_name"],
                description="",
                entity_uuid="",
                entity_value="",
                entity_type=row["entity_type"],
                contributing_events=(),
            )
            pattern_key = derive_pattern_key(key_alert)
            ids_raw = row["alert_ids"] or []
            id_tuple = tuple(ids_raw)[:_AGG_MAX_CONTRIB_IDS]
            out.append(
                PatternFeedbackRow(
                    pattern_key=pattern_key,
                    tp_count=int(row["tp_count"]),
                    most_recent_tp_ns=int(row["most_recent_tp_ns"]),
                    contributing_alert_ids=id_tuple,
                )
            )
        return tuple(out)

    async def count_by_severity(self) -> dict[str, int]:
        """Return alert counts grouped by severity name (lowercase)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT severity_id, COUNT(*) FROM alerts GROUP BY severity_id"
            )
        counts: dict[str, int] = {}
        for row in rows:
            severity_id = row[0]
            count = int(row[1])
            try:
                name = SeverityLevel(int(severity_id)).name.lower()
            except (ValueError, TypeError):
                name = "unknown"
            counts[name] = counts.get(name, 0) + count
        return counts
