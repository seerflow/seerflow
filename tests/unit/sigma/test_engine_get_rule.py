"""Unit tests for SigmaEngine.get_rule O(1) lookup (S-154 Task 3)."""

from __future__ import annotations

import pytest

from seerflow.sigma.engine import SigmaEngine


def _bundled_engine() -> SigmaEngine:
    engine = SigmaEngine()
    engine.load_bundled()
    return engine


@pytest.mark.unit
def test_get_rule_returns_rule_dict_for_known_id() -> None:
    engine = _bundled_engine()
    sample = engine.list_rules()[0]
    fetched = engine.get_rule(sample["rule_id"])
    assert fetched is not None
    assert fetched["rule_id"] == sample["rule_id"]
    assert fetched["title"] == sample["title"]


@pytest.mark.unit
def test_get_rule_returns_none_for_unknown_id() -> None:
    engine = _bundled_engine()
    assert engine.get_rule("no-such-rule") is None


@pytest.mark.unit
def test_get_rule_reflects_set_enabled_state() -> None:
    engine = _bundled_engine()
    sample = engine.list_rules()[0]
    engine.set_enabled(sample["rule_id"], False)
    fetched = engine.get_rule(sample["rule_id"])
    assert fetched is not None
    assert fetched["enabled"] is False
