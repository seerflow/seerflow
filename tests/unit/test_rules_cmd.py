"""Unit tests for seerflow.rules_cmd: collection, filtering, output."""

from __future__ import annotations

import argparse
import json

import pytest

from seerflow.models.event import SeverityLevel
from seerflow.rules_cmd import (
    _apply_filters,
    _rules_from_engine,
    run_rules_list,
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


# ---------------------------------------------------------------------------
# End-to-end run_rules_list behavior tests (Task 5)
# ---------------------------------------------------------------------------


def _ns(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "command": "rules",
        "rules_cmd": "list",
        "technique": None,
        "tactic": None,
        "format": "table",
        "config": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture
def stub_engine(monkeypatch: pytest.MonkeyPatch) -> list[CompiledRule]:
    """Replace SigmaEngine.load_bundled/load_custom with a fixed rule set."""
    rules = [
        _make_rule(
            "Suspicious Scheduled Task",
            tactics=("persistence",),
            techniques=("T1053.005",),
            logsource=("process_creation", "windows", ""),
            severity=SeverityLevel.ERROR,
            description="Detects scheduled task creation",
        ),
        _make_rule(
            "LSASS Memory Dump",
            tactics=("credential_access",),
            techniques=("T1003.001",),
            logsource=("process_access", "windows", ""),
            severity=SeverityLevel.CRITICAL,
            description="Detects LSASS memory access",
        ),
        _make_rule(
            "SMB Lateral Move",
            tactics=("lateral_movement",),
            techniques=("T1021",),
            logsource=("network_connection", "windows", ""),
            severity=SeverityLevel.WARNING,
            description="Detects SMB lateral movement",
        ),
    ]

    def _fake_load_bundled(self: SigmaEngine) -> None:
        for r in rules:
            self._index.setdefault(r.logsource_key, []).append(r)
            self._rule_count += 1

    def _fake_load_custom(self: SigmaEngine, dirs: object) -> None:
        return None

    monkeypatch.setattr(SigmaEngine, "load_bundled", _fake_load_bundled)
    monkeypatch.setattr(SigmaEngine, "load_custom", _fake_load_custom)
    monkeypatch.setattr(
        "seerflow.config.load_config",
        lambda path: (_ for _ in ()).throw(FileNotFoundError()),
    )

    return rules


def test_run_rules_list_table_no_filter(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Suspicious Scheduled Task" in out
    assert "LSASS Memory Dump" in out
    assert "SMB Lateral Move" in out
    assert "3 rules loaded, 3 matching filter" in out


def test_run_rules_list_table_technique_prefix(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(technique="T1053"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Suspicious Scheduled Task" in out
    assert "LSASS Memory Dump" not in out
    assert "3 rules loaded, 1 matching filter" in out


def test_run_rules_list_table_tactic_by_id(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(tactic="TA0008"))  # lateral_movement
    assert rc == 0
    out = capsys.readouterr().out
    assert "SMB Lateral Move" in out
    assert "Suspicious Scheduled Task" not in out
    assert "3 rules loaded, 1 matching filter" in out


def test_run_rules_list_json(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(format="json"))
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert len(payload) == 3
    names = {entry["name"] for entry in payload}
    assert names == {
        "Suspicious Scheduled Task",
        "LSASS Memory Dump",
        "SMB Lateral Move",
    }
    one = next(e for e in payload if e["name"] == "LSASS Memory Dump")
    assert one["severity"] == "CRITICAL"
    assert one["logsource"] == {
        "category": "process_access",
        "product": "windows",
        "service": "",
    }
    assert one["techniques"] == ["T1003.001"]


def test_run_rules_list_json_no_matches_returns_empty_array(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(technique="T9999", format="json"))
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_run_rules_list_rejects_bad_technique(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(technique="foo"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid technique 'foo'" in err


def test_run_rules_list_rejects_unknown_tactic(
    stub_engine: list[CompiledRule],
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = run_rules_list(_ns(tactic="not_real"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown tactic 'not_real'" in err
    assert "persistence" in err


def test_run_rules_list_no_rules_loaded_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(SigmaEngine, "load_bundled", lambda self: None)
    monkeypatch.setattr(SigmaEngine, "load_custom", lambda self, dirs: None)
    monkeypatch.setattr(
        "seerflow.config.load_config",
        lambda path: (_ for _ in ()).throw(FileNotFoundError()),
    )

    rc = run_rules_list(_ns())
    assert rc == 0
    out = capsys.readouterr().out
    assert "No rules loaded." in out
    assert "0 rules loaded, 0 matching filter" in out
