"""Unit tests for seerflow.rules_cmd: collection, filtering, output."""

from __future__ import annotations

from seerflow.models.event import SeverityLevel
from seerflow.rules_cmd import (
    _apply_filters,
    _rules_from_engine,
    run_rules_list,  # noqa: F401 — part of public API, integration-tested in Task 4
)
from seerflow.sigma.engine import SigmaEngine
from seerflow.sigma.matcher import CompiledRule


def _make_rule(
    name: str,
    *,
    tactics: tuple[str, ...] = (),
    techniques: tuple[str, ...] = (),
    logsource: tuple[str, str, str] = ("", "", ""),
    severity: SeverityLevel = SeverityLevel.WARNING,
    description: str = "",
) -> CompiledRule:
    return CompiledRule(
        rule_name=name,
        description=description,
        severity=severity,
        attack_tactics=tactics,
        attack_techniques=techniques,
        logsource_key=logsource,
        _rule=None,  # type: ignore[arg-type]
    )


def test_rules_from_engine_empty_engine_returns_empty_list() -> None:
    engine = SigmaEngine()
    assert _rules_from_engine(engine) == []


def test_apply_filters_no_filters_returns_all() -> None:
    r1 = _make_rule("A")
    r2 = _make_rule("B")
    assert _apply_filters([r1, r2], technique=None, tactic_name=None) == [r1, r2]


def test_apply_filters_technique_exact_match() -> None:
    r1 = _make_rule("A", techniques=("T1053.005",))
    r2 = _make_rule("B", techniques=("T1059",))
    assert _apply_filters([r1, r2], technique="T1053.005", tactic_name=None) == [r1]


def test_apply_filters_technique_prefix_includes_subtechniques() -> None:
    r1 = _make_rule("A", techniques=("T1053",))
    r2 = _make_rule("B", techniques=("T1053.005",))
    r3 = _make_rule("C", techniques=("T10530",))
    result = _apply_filters([r1, r2, r3], technique="T1053", tactic_name=None)
    assert result == [r1, r2]


def test_apply_filters_tactic_by_canonical_name() -> None:
    r1 = _make_rule("A", tactics=("persistence",))
    r2 = _make_rule("B", tactics=("discovery",))
    assert _apply_filters([r1, r2], technique=None, tactic_name="persistence") == [r1]


def test_apply_filters_technique_and_tactic_is_and() -> None:
    r1 = _make_rule("A", tactics=("persistence",), techniques=("T1053.005",))
    r2 = _make_rule("B", tactics=("persistence",), techniques=("T1059",))
    r3 = _make_rule("C", tactics=("discovery",), techniques=("T1053.005",))
    result = _apply_filters([r1, r2, r3], technique="T1053", tactic_name="persistence")
    assert result == [r1]
