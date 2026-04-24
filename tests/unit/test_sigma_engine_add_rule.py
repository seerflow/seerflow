"""Tests for SigmaEngine.add_rule + validate_rule (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.sigma.engine import SigmaEngine, SigmaRuleCollisionError
from seerflow.sigma.validator import SigmaRuleValidationError

if TYPE_CHECKING:
    from pathlib import Path

_NEW_YAML = """
title: New Rule S151 Add
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 'add-test-token'
  condition: sel
"""


def test_add_rule_indexes_persists_returns_id(tmp_path: Path) -> None:
    e = SigmaEngine()
    rid = e.add_rule(_NEW_YAML, tmp_path / "new.yml")
    assert any(r.rule_id == rid for r in e.iter_compiled_rules())
    assert (tmp_path / "new.yml").read_text() == _NEW_YAML
    assert len(rid) == 36


def test_add_rule_invalid_raises_validation_error_no_persist(tmp_path: Path) -> None:
    e = SigmaEngine()
    with pytest.raises(SigmaRuleValidationError):
        e.add_rule("not yaml: [", tmp_path / "bad.yml")
    assert not (tmp_path / "bad.yml").exists()


def test_add_rule_collision_raises_no_persist(tmp_path: Path) -> None:
    e = SigmaEngine()
    e.add_rule(_NEW_YAML, tmp_path / "a.yml", source_kind="custom_uploaded")
    with pytest.raises(SigmaRuleCollisionError) as exc:
        e.add_rule(_NEW_YAML, tmp_path / "b.yml", source_kind="custom_uploaded")
    assert exc.value.existing_source == "custom_uploaded"
    assert not (tmp_path / "b.yml").exists()


def test_validate_rule_does_not_persist() -> None:
    e = SigmaEngine()
    meta = e.validate_rule(_NEW_YAML)
    assert meta["title"] == "New Rule S151 Add"
    assert isinstance(meta["rule_id"], str)
    assert list(e.iter_compiled_rules()) == []


def test_validate_rule_raises_on_invalid() -> None:
    e = SigmaEngine()
    with pytest.raises(SigmaRuleValidationError):
        e.validate_rule("not yaml: [")


def test_add_rule_makes_parent_dirs(tmp_path: Path) -> None:
    e = SigmaEngine()
    target = tmp_path / "nested" / "dir" / "rule.yml"
    e.add_rule(_NEW_YAML, target)
    assert target.exists()
