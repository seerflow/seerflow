"""Tests for SigmaEngine.list_rules + match counters + flush (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.sigma.engine import SigmaEngine
from seerflow.sigma.state import SigmaRuleState
from tests.helpers import make_event

if TYPE_CHECKING:
    from pathlib import Path

_YAML = """
title: TX S151 Counters
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 'tx-s151'
  condition: sel
"""


@pytest.fixture
def engine(tmp_path: Path) -> SigmaEngine:
    p = tmp_path / "tx.yml"
    p.write_text(_YAML)
    e = SigmaEngine()
    e.load_rules([p])
    return e


def test_list_rules_returns_summary(engine: SigmaEngine) -> None:
    summaries = engine.list_rules()
    assert len(summaries) == 1
    s = summaries[0]
    assert {
        "rule_id",
        "title",
        "severity",
        "logsource_key",
        "enabled",
        "match_count_lifetime",
        "last_fired_ns",
        "source",
        "yaml_source",
        "attack_tactics",
        "attack_techniques",
    } <= set(s.keys())
    assert s["enabled"] is True
    assert s["source"] == "bundled"
    assert s["match_count_lifetime"] == 0
    assert s["last_fired_ns"] is None


def test_match_counter_increments_on_evaluate(engine: SigmaEngine) -> None:
    event = make_event(
        message="found tx-s151",
        log_source_product="linux",
        log_source_category="process_creation",
    )
    engine.evaluate(event)
    engine.evaluate(event)
    summaries = engine.list_rules()
    assert summaries[0]["match_count_lifetime"] == 2
    assert summaries[0]["last_fired_ns"] is not None


def test_disabled_rule_does_not_increment_counter(engine: SigmaEngine) -> None:
    rid = engine.list_rules()[0]["rule_id"]
    engine.set_enabled(rid, False)
    event = make_event(
        message="found tx-s151",
        log_source_product="linux",
        log_source_category="process_creation",
    )
    engine.evaluate(event)
    assert engine.list_rules()[0]["match_count_lifetime"] == 0


class _FakeStateStore:
    """In-memory ``SigmaRuleStateStore`` for tests."""

    def __init__(self) -> None:
        self.states: dict[str, SigmaRuleState] = {}
        self.last_deltas: dict[str, tuple[int, int]] = {}

    async def get_all(self) -> dict[str, SigmaRuleState]:
        return dict(self.states)

    async def set_enabled(self, rule_id: str, enabled: bool) -> None:
        prev = self.states.get(rule_id)
        self.states[rule_id] = SigmaRuleState(
            rule_id=rule_id,
            enabled=enabled,
            match_count_lifetime=prev.match_count_lifetime if prev else 0,
            last_fired_ns=prev.last_fired_ns if prev else None,
            updated_at_ns=1,
        )

    async def increment_counts(self, deltas) -> None:  # type: ignore[no-untyped-def]
        self.last_deltas = dict(deltas)
        for rid, (delta, lfn) in deltas.items():
            prev = self.states.get(rid)
            self.states[rid] = SigmaRuleState(
                rule_id=rid,
                enabled=prev.enabled if prev else True,
                match_count_lifetime=(prev.match_count_lifetime if prev else 0) + delta,
                last_fired_ns=max(prev.last_fired_ns or 0, lfn) if prev else lfn,
                updated_at_ns=1,
            )


async def test_attach_state_store_hydrates_disabled_set(engine: SigmaEngine) -> None:
    rid = engine.list_rules()[0]["rule_id"]
    store = _FakeStateStore()
    store.states[rid] = SigmaRuleState(
        rule_id=rid,
        enabled=False,
        match_count_lifetime=42,
        last_fired_ns=999,
        updated_at_ns=1,
    )
    await engine.attach_state_store(store)
    summaries = engine.list_rules()
    assert summaries[0]["enabled"] is False
    assert summaries[0]["match_count_lifetime"] == 42
    assert summaries[0]["last_fired_ns"] == 999


async def test_flush_counters_writes_deltas(engine: SigmaEngine) -> None:
    store = _FakeStateStore()
    await engine.attach_state_store(store)
    event = make_event(
        message="found tx-s151",
        log_source_product="linux",
        log_source_category="process_creation",
    )
    engine.evaluate(event)
    engine.evaluate(event)

    await engine.flush_counters()

    rid = engine.list_rules()[0]["rule_id"]
    assert store.last_deltas[rid][0] == 2
    assert engine._match_counts[rid] == 0


async def test_flush_counters_noop_without_store(engine: SigmaEngine) -> None:
    # No store attached → no-op even with pending counts
    event = make_event(
        message="found tx-s151",
        log_source_product="linux",
        log_source_category="process_creation",
    )
    engine.evaluate(event)
    await engine.flush_counters()
