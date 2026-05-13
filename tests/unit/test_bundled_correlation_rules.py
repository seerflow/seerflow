"""Tests for bundled correlation rule discovery and validation."""

from __future__ import annotations

from pathlib import Path

from seerflow.correlation.bundled import get_bundled_rule_dir
from seerflow.correlation.rule_loader import load_correlation_rules


class TestGetBundledRuleDir:
    def test_returns_path_to_rules_directory(self) -> None:
        rule_dir = get_bundled_rule_dir()
        assert isinstance(rule_dir, Path)
        assert rule_dir.is_dir()

    def test_directory_contains_yml_files(self) -> None:
        rule_dir = get_bundled_rule_dir()
        yml_files = list(rule_dir.glob("*.yml"))
        assert len(yml_files) >= 5


class TestBuiltinRulesLoadAndValidate:
    """All 5 bundled rules must parse without errors."""

    def test_all_bundled_rules_load_successfully(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        assert len(rules) == 5
        names = {r.name for r in rules}
        assert names == {
            "data-exfiltration",
            "brute-force-lateral-movement",
            "credential-stuffing",
            "privilege-escalation-chain",
            "c2-beaconing",
        }

    def test_all_rules_have_mitre_mapping(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        for rule in rules:
            assert len(rule.mitre_tactics) >= 1, f"{rule.name} missing mitre_tactics"
            assert len(rule.mitre_techniques) >= 1, f"{rule.name} missing mitre_techniques"

    def test_all_rules_have_descriptions(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        for rule in rules:
            assert rule.description, f"{rule.name} has empty description"

    def test_exfiltration_rule_structure(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        rule = next(r for r in rules if r.name == "data-exfiltration")
        assert rule.entity_type == "ip"
        assert rule.window_seconds == 900
        assert rule.min_sources == 2
        assert len(rule.sources) == 2
        assert rule.alert_severity.value == 5

    def test_brute_force_rule_structure(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        rule = next(r for r in rules if r.name == "brute-force-lateral-movement")
        assert rule.entity_type == "user"
        assert rule.window_seconds == 600
        assert rule.min_sources == 2
        assert rule.sources[0].min_count == 5
        assert rule.sources[1].min_count == 1

    def test_credential_stuffing_rule_structure(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        rule = next(r for r in rules if r.name == "credential-stuffing")
        assert rule.entity_type == "ip"
        assert rule.window_seconds == 300
        assert rule.min_sources == 1
        assert rule.sources[0].min_count == 10
        assert rule.alert_severity.value == 4

    def test_privilege_escalation_rule_structure(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        rule = next(r for r in rules if r.name == "privilege-escalation-chain")
        assert rule.entity_type == "user"
        assert rule.window_seconds == 600
        assert rule.min_sources == 2

    def test_c2_beaconing_rule_structure(self) -> None:
        rules = load_correlation_rules([str(get_bundled_rule_dir())])
        rule = next(r for r in rules if r.name == "c2-beaconing")
        assert rule.entity_type == "ip"
        assert rule.window_seconds == 1800
        assert rule.min_sources == 1
        assert rule.sources[0].min_count == 5
        assert rule.alert_severity.value == 5
