"""PostgreSQL implementation of ``SigmaRuleStateStore`` (S-073).

Mixin pattern mirrors :class:`seerflow.storage._sqlite_sigma_state._SqliteSigmaStateMixin`
— composes onto :class:`seerflow.storage.postgres.PostgresBackend` so the
backend itself satisfies the ``SigmaRuleStateStore`` Protocol.

All operations acquire a connection from the backend's asyncpg pool and
return immediately; there is no per-method transaction. The upsert SQL
uses ``ON CONFLICT (rule_id) DO UPDATE`` for both ``set_enabled`` and
``record_match``, matching the SQLite semantics exactly.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from seerflow.sigma.state import SigmaRuleState

if TYPE_CHECKING:
    from collections.abc import Mapping

    import asyncpg


_SELECT_ALL_SQL = (
    "SELECT rule_id, enabled, match_count_lifetime, last_fired_ns, updated_at_ns "
    "FROM sigma_rule_state"
)

_UPSERT_ENABLED_SQL = """
INSERT INTO sigma_rule_state (rule_id, enabled, updated_at_ns)
VALUES ($1, $2, $3)
ON CONFLICT (rule_id) DO UPDATE
    SET enabled = EXCLUDED.enabled,
        updated_at_ns = EXCLUDED.updated_at_ns
"""

_UPSERT_COUNT_SQL = """
INSERT INTO sigma_rule_state
    (rule_id, enabled, match_count_lifetime, last_fired_ns, updated_at_ns)
VALUES ($1, 1, $2, $3, $4)
ON CONFLICT (rule_id) DO UPDATE
    SET match_count_lifetime = sigma_rule_state.match_count_lifetime
        + EXCLUDED.match_count_lifetime,
        last_fired_ns = GREATEST(
            COALESCE(sigma_rule_state.last_fired_ns, 0),
            EXCLUDED.last_fired_ns
        ),
        updated_at_ns = EXCLUDED.updated_at_ns
"""


class _PostgresSigmaStateMixin:
    """Mixin providing ``SigmaRuleStateStore`` methods backed by PostgreSQL."""

    __slots__: tuple[str, ...] = ()

    _pool: asyncpg.Pool  # supplied by the composing PostgresBackend

    async def set_enabled(self, rule_id: str, enabled: bool) -> None:
        """Toggle the enabled flag for a Sigma rule (upsert)."""
        now_ns = time.time_ns()
        async with self._pool.acquire() as conn:
            await conn.execute(_UPSERT_ENABLED_SQL, rule_id, 1 if enabled else 0, now_ns)

    async def record_match(
        self,
        rule_id: str,
        count: int,
        last_fired_ns: int,
    ) -> None:
        """Increment the lifetime match count + update last_fired_ns."""
        now_ns = time.time_ns()
        async with self._pool.acquire() as conn:
            await conn.execute(_UPSERT_COUNT_SQL, rule_id, count, last_fired_ns, now_ns)

    async def list_all_states(self) -> Mapping[str, SigmaRuleState]:
        """Return every persisted rule state keyed by ``rule_id``."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_ALL_SQL)
        return {
            row["rule_id"]: SigmaRuleState(
                rule_id=row["rule_id"],
                enabled=bool(row["enabled"]),
                match_count_lifetime=int(row["match_count_lifetime"]),
                last_fired_ns=(
                    int(row["last_fired_ns"]) if row["last_fired_ns"] is not None else None
                ),
                updated_at_ns=int(row["updated_at_ns"]),
            )
            for row in rows
        }
