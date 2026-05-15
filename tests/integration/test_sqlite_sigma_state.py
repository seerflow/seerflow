"""Integration tests for the SQLite SigmaRuleStateStore impl (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.sigma.state import SigmaRuleState

if TYPE_CHECKING:
    from seerflow.storage.sqlite import SqliteBackend


async def test_set_enabled_and_get_all(backend: SqliteBackend) -> None:
    await backend.set_enabled("rule-a", False)
    states = await backend.get_all()
    assert "rule-a" in states
    assert states["rule-a"].enabled is False
    assert states["rule-a"].match_count_lifetime == 0


async def test_set_enabled_idempotent(backend: SqliteBackend) -> None:
    await backend.set_enabled("rule-b", False)
    await backend.set_enabled("rule-b", False)
    await backend.set_enabled("rule-b", True)
    states = await backend.get_all()
    assert states["rule-b"].enabled is True


async def test_increment_counts_upserts_and_max_last_fired(backend: SqliteBackend) -> None:
    await backend.increment_counts({"r": (5, 100)})
    await backend.increment_counts({"r": (3, 50)})  # older last_fired_ns
    await backend.increment_counts({"r": (2, 200)})
    states = await backend.get_all()
    assert states["r"].match_count_lifetime == 10
    assert states["r"].last_fired_ns == 200


async def test_increment_counts_empty_is_noop(backend: SqliteBackend) -> None:
    await backend.increment_counts({})
    assert await backend.get_all() == {}


async def test_state_dataclass_returned(backend: SqliteBackend) -> None:
    await backend.set_enabled("rule-c", True)
    states = await backend.get_all()
    assert isinstance(states["rule-c"], SigmaRuleState)
