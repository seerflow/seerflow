"""Tests for the SigmaRuleState dataclass + Protocol (S-151)."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import get_type_hints

from seerflow.sigma.state import SigmaRuleState, SigmaRuleStateStore


def test_sigma_rule_state_is_frozen_dataclass() -> None:
    assert is_dataclass(SigmaRuleState)
    hints = get_type_hints(SigmaRuleState)
    assert {
        "rule_id",
        "enabled",
        "match_count_lifetime",
        "last_fired_ns",
        "updated_at_ns",
    } <= hints.keys()


def test_sigma_rule_state_immutable() -> None:
    s = SigmaRuleState(
        rule_id="r", enabled=True, match_count_lifetime=0, last_fired_ns=None, updated_at_ns=1
    )
    try:
        s.enabled = False  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("SigmaRuleState should be frozen")


def test_state_store_protocol_methods() -> None:
    methods = {m for m in dir(SigmaRuleStateStore) if not m.startswith("_")}
    assert {"get_all", "set_enabled", "increment_counts"} <= methods
