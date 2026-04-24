"""Tests for SigmaEngine copy-on-write set_enabled (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.sigma.engine import SigmaEngine
from tests.helpers import make_event

if TYPE_CHECKING:
    from pathlib import Path

_WHOAMI_YAML = """
title: Whoami Test S151
logsource:
  product: linux
  category: process_creation
detection:
  sel:
    message|contains: 'whoami'
  condition: sel
"""


@pytest.fixture
def engine_with_whoami(tmp_path: Path) -> SigmaEngine:
    rule_path = tmp_path / "whoami.yml"
    rule_path.write_text(_WHOAMI_YAML)
    engine = SigmaEngine()
    engine.load_rules([rule_path])
    return engine


def _make_match_event() -> object:
    return make_event(
        message="user ran whoami",
        log_source_product="linux",
        log_source_category="process_creation",
    )


def test_set_enabled_false_skips_rule(engine_with_whoami: SigmaEngine) -> None:
    engine = engine_with_whoami
    rid = next(engine.iter_compiled_rules()).rule_id
    assert len(engine.evaluate(_make_match_event())) == 1
    engine.set_enabled(rid, False)
    assert engine.evaluate(_make_match_event()) == []


def test_set_enabled_true_re_enables(engine_with_whoami: SigmaEngine) -> None:
    engine = engine_with_whoami
    rid = next(engine.iter_compiled_rules()).rule_id
    engine.set_enabled(rid, False)
    engine.set_enabled(rid, True)
    assert len(engine.evaluate(_make_match_event())) == 1


def test_set_enabled_unknown_rule_id_is_noop(engine_with_whoami: SigmaEngine) -> None:
    engine = engine_with_whoami
    engine.set_enabled("nonexistent-id", False)
    assert len(engine.evaluate(_make_match_event())) == 1


def test_disabled_rule_ids_is_frozen(engine_with_whoami: SigmaEngine) -> None:
    engine = engine_with_whoami
    rid = next(engine.iter_compiled_rules()).rule_id
    engine.set_enabled(rid, False)
    assert isinstance(engine._disabled_rule_ids, frozenset)
    assert rid in engine._disabled_rule_ids
