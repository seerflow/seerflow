"""SQLite implementation of ``SigmaRuleStateStore`` (S-151).

Mixin pattern mirrors ``_SqliteAlertMixin`` — composes onto ``SqliteBackend``
so the backend itself satisfies the ``SigmaRuleStateStore`` Protocol.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from seerflow.sigma.state import SigmaRuleState

if TYPE_CHECKING:
    from collections.abc import Mapping

    import aiosqlite


_SELECT_ALL_SQL = (
    "SELECT rule_id, enabled, match_count_lifetime, last_fired_ns, updated_at_ns "
    "FROM sigma_rule_state"
)

_UPSERT_ENABLED_SQL = """
INSERT INTO sigma_rule_state (rule_id, enabled, updated_at_ns)
VALUES (?, ?, ?)
ON CONFLICT(rule_id) DO UPDATE
    SET enabled = excluded.enabled,
        updated_at_ns = excluded.updated_at_ns
"""

_UPSERT_COUNT_SQL = """
INSERT INTO sigma_rule_state
    (rule_id, enabled, match_count_lifetime, last_fired_ns, updated_at_ns)
VALUES (?, 1, ?, ?, ?)
ON CONFLICT(rule_id) DO UPDATE
    SET match_count_lifetime = match_count_lifetime + excluded.match_count_lifetime,
        last_fired_ns = MAX(COALESCE(last_fired_ns, 0), excluded.last_fired_ns),
        updated_at_ns = excluded.updated_at_ns
"""


class _SqliteSigmaStateMixin:
    """Mixin providing ``SigmaRuleStateStore`` methods backed by SQLite."""

    # Empty slots so the composed ``SqliteBackend`` keeps its slot discipline
    # — mirrors ``_SqliteAlertMixin``.
    __slots__: tuple[str, ...] = ()

    _conn: aiosqlite.Connection  # supplied by composing class

    async def get_all(self) -> dict[str, SigmaRuleState]:
        async with await self._conn.execute(_SELECT_ALL_SQL) as cursor:
            rows = await cursor.fetchall()
        return {
            row[0]: SigmaRuleState(
                rule_id=row[0],
                enabled=bool(row[1]),
                match_count_lifetime=int(row[2]),
                last_fired_ns=int(row[3]) if row[3] is not None else None,
                updated_at_ns=int(row[4]),
            )
            for row in rows
        }

    async def set_enabled(self, rule_id: str, enabled: bool) -> None:
        now_ns = time.time_ns()
        await self._conn.execute(_UPSERT_ENABLED_SQL, (rule_id, 1 if enabled else 0, now_ns))
        await self._conn.commit()

    async def increment_counts(
        self,
        deltas: Mapping[str, tuple[int, int]],
    ) -> None:
        if not deltas:
            return
        now_ns = time.time_ns()
        rows = [
            (rule_id, delta, last_fired_ns, now_ns)
            for rule_id, (delta, last_fired_ns) in deltas.items()
        ]
        await self._conn.executemany(_UPSERT_COUNT_SQL, rows)
        await self._conn.commit()
