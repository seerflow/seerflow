"""Tests for correlation rule YAML parsing and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.correlation.rule_loader import RuleValidationError, parse_rule_yaml

VALID_RULE: dict[str, object] = {
    "name": "ssh-brute-force",
    "entity_type": "ip",
    "window_seconds": 1800,
    "min_sources": 2,
    "alert_severity": 4,
    "sources": [
        {
            "source_type": "syslog",
            "conditions": {"message": "Failed password.*"},
            "min_count": 5,
        },
        {
            "source_type": "syslog",
            "conditions": {"message": "Accepted.*"},
            "min_count": 1,
        },
    ],
}


class TestParseRuleYaml:
    def test_valid_rule_returns_correlation_rule(self) -> None:
        rule = parse_rule_yaml(VALID_RULE)
        assert rule.name == "ssh-brute-force"
        assert rule.entity_type == "ip"
        assert rule.window_seconds == 1800

    def test_missing_name_raises(self) -> None:
        data = {**VALID_RULE}
        del data["name"]
        with pytest.raises(RuleValidationError, match="name"):
            parse_rule_yaml(data)

    def test_invalid_entity_type_raises(self) -> None:
        data = {**VALID_RULE, "entity_type": "invalid"}
        with pytest.raises(RuleValidationError, match="entity_type"):
            parse_rule_yaml(data)

    def test_window_seconds_must_be_positive(self) -> None:
        data = {**VALID_RULE, "window_seconds": 0}
        with pytest.raises(RuleValidationError, match="window_seconds"):
            parse_rule_yaml(data)

    def test_invalid_regex_in_conditions_raises(self) -> None:
        data = {
            **VALID_RULE,
            "sources": [
                {
                    "source_type": "syslog",
                    "conditions": {"message": "[invalid"},
                    "min_count": 1,
                },
            ],
        }
        with pytest.raises(RuleValidationError, match="regex"):
            parse_rule_yaml(data)

    def test_pattern_too_long_raises(self) -> None:
        data = {
            **VALID_RULE,
            "sources": [
                {
                    "source_type": "syslog",
                    "conditions": {"message": "a" * 513},
                    "min_count": 1,
                },
            ],
        }
        with pytest.raises(RuleValidationError, match="512"):
            parse_rule_yaml(data)

    def test_optional_fields_have_defaults(self) -> None:
        rule = parse_rule_yaml(VALID_RULE)
        assert rule.description == ""
        assert rule.mitre_tactics == ()
        assert rule.mitre_techniques == ()

    def test_mitre_tags_parsed(self) -> None:
        data = {
            **VALID_RULE,
            "mitre_tactics": ["credential-access"],
            "mitre_techniques": ["T1110.001"],
        }
        rule = parse_rule_yaml(data)
        assert rule.mitre_tactics == ("credential-access",)
        assert rule.mitre_techniques == ("T1110.001",)

    def test_sources_parsed_correctly(self) -> None:
        rule = parse_rule_yaml(VALID_RULE)
        assert len(rule.sources) == 2
        assert rule.sources[0].source_type == "syslog"
        assert rule.sources[0].conditions == {"message": "Failed password.*"}
        assert rule.sources[0].min_count == 5
        assert rule.sources[1].min_count == 1

    def test_min_sources_default(self) -> None:
        data = {**VALID_RULE}
        del data["min_sources"]
        rule = parse_rule_yaml(data)
        assert rule.min_sources == 1

    def test_alert_severity_returns_enum(self) -> None:
        rule = parse_rule_yaml(VALID_RULE)
        from seerflow.models.event import SeverityLevel

        assert rule.alert_severity == SeverityLevel.ERROR
        assert rule.alert_severity.value == 4

    def test_empty_sources_raises(self) -> None:
        data = {**VALID_RULE, "sources": []}
        with pytest.raises(RuleValidationError, match="source"):
            parse_rule_yaml(data)

    def test_min_sources_exceeds_sources_raises(self) -> None:
        data = {**VALID_RULE, "min_sources": 5}
        with pytest.raises(RuleValidationError):
            parse_rule_yaml(data)

    def test_alert_severity_out_of_range_raises(self) -> None:
        data = {**VALID_RULE, "alert_severity": 7}
        with pytest.raises(RuleValidationError, match="alert_severity"):
            parse_rule_yaml(data)

    def test_source_missing_source_type_raises(self) -> None:
        data = {
            **VALID_RULE,
            "sources": [{"conditions": {"message": ".*"}, "min_count": 1}],
        }
        with pytest.raises(RuleValidationError, match="source_type"):
            parse_rule_yaml(data)

    def test_description_preserved(self) -> None:
        data = {**VALID_RULE, "description": "Detect SSH brute force"}
        rule = parse_rule_yaml(data)
        assert rule.description == "Detect SSH brute force"

    def test_negative_window_seconds_raises(self) -> None:
        data = {**VALID_RULE, "window_seconds": -10}
        with pytest.raises(RuleValidationError, match="window_seconds"):
            parse_rule_yaml(data)

    def test_window_seconds_non_int_raises(self) -> None:
        data = {**VALID_RULE, "window_seconds": 3.5}
        with pytest.raises(RuleValidationError, match="window_seconds"):
            parse_rule_yaml(data)


class TestLoadCorrelationRules:
    def test_loads_rules_from_directory(self, tmp_path: Path) -> None:
        from seerflow.correlation.rule_loader import load_correlation_rules

        rule_file = tmp_path / "test_rule.yml"
        rule_file.write_text(
            """
name: test-rule
entity_type: ip
window_seconds: 1800
min_sources: 1
alert_severity: 4
sources:
  - source_type: syslog
    conditions:
      message: "test.*"
    min_count: 1
"""
        )
        rules = load_correlation_rules([str(tmp_path)])
        assert len(rules) == 1
        assert rules[0].name == "test-rule"

    def test_skips_invalid_rules_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from seerflow.correlation.rule_loader import load_correlation_rules

        bad_file = tmp_path / "bad.yml"
        bad_file.write_text("name: missing_required_fields\n")
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            rules = load_correlation_rules([str(tmp_path)])
        assert len(rules) == 0
        assert "bad.yml" in caplog.text

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        from seerflow.correlation.rule_loader import load_correlation_rules

        rules = load_correlation_rules([str(tmp_path)])
        assert rules == []

    def test_nonexistent_directory_skipped(self) -> None:
        from seerflow.correlation.rule_loader import load_correlation_rules

        rules = load_correlation_rules(["/nonexistent/path"])
        assert rules == []

    def test_multiple_directories(self, tmp_path: Path) -> None:
        from seerflow.correlation.rule_loader import load_correlation_rules

        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir1 / "rule1.yml").write_text(
            """
name: rule1
entity_type: ip
window_seconds: 600
min_sources: 1
alert_severity: 3
sources:
  - source_type: syslog
    conditions:
      message: "pattern1.*"
    min_count: 1
"""
        )
        (dir2 / "rule2.yml").write_text(
            """
name: rule2
entity_type: user
window_seconds: 300
min_sources: 1
alert_severity: 5
sources:
  - source_type: file
    conditions:
      message: "pattern2.*"
    min_count: 1
"""
        )
        rules = load_correlation_rules([str(dir1), str(dir2)])
        assert len(rules) == 2
        names = {r.name for r in rules}
        assert names == {"rule1", "rule2"}


def _rule_data(**overrides: object) -> dict[str, object]:
    """Return a minimal valid rule dict, optionally overriding fields."""
    base: dict[str, object] = {
        "name": "brute-force-1",
        "entity_type": "ip",
        "window_seconds": 600,
        "min_sources": 1,
        "alert_severity": 3,
        "sources": [
            {
                "source_type": "syslog",
                "conditions": {"message": "test.*"},
                "min_count": 1,
            }
        ],
    }
    return {**base, **overrides}


class TestRuleNameValidation:
    """S-156: Rule name format validation."""

    def test_valid_hyphenated_name_accepted(self) -> None:
        rule = parse_rule_yaml(_rule_data(name="brute-force-1"))
        assert rule.name == "brute-force-1"

    def test_valid_all_lowercase_alphanumeric_accepted(self) -> None:
        rule = parse_rule_yaml(_rule_data(name="ab"))
        assert rule.name == "ab"

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name="Brute-Force"))

    def test_underscore_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name="brute_force"))

    def test_leading_hyphen_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name="-brute-force"))

    def test_trailing_hyphen_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name="brute-force-"))

    def test_too_long_rejected(self) -> None:
        long_name = "a" + "-" * 62 + "b"  # 64 chars — valid boundary
        rule = parse_rule_yaml(_rule_data(name=long_name))
        assert rule.name == long_name

    def test_over_max_length_rejected(self) -> None:
        over_name = "a" * 65  # 65 chars — one over max
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name=over_name))

    def test_single_char_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="Invalid rule name"):
            parse_rule_yaml(_rule_data(name="a"))


class TestWindowSecondsUpperBound:
    """S-156: window_seconds max 604800 (7 days) validation."""

    def test_max_window_accepted(self) -> None:
        rule = parse_rule_yaml(_rule_data(window_seconds=604_800))
        assert rule.window_seconds == 604_800

    def test_one_below_max_accepted(self) -> None:
        rule = parse_rule_yaml(_rule_data(window_seconds=604_799))
        assert rule.window_seconds == 604_799

    def test_over_max_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="window_seconds must be <="):
            parse_rule_yaml(_rule_data(window_seconds=604_801))

    def test_well_over_max_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="window_seconds must be <="):
            parse_rule_yaml(_rule_data(window_seconds=9_999_999))


class TestMitreValidation:
    """S-156: MITRE tactics/techniques must be non-empty strings."""

    def test_non_string_tactic_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="mitre_tactics"):
            parse_rule_yaml(_rule_data(mitre_tactics=[123]))

    def test_empty_string_tactic_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="mitre_tactics"):
            parse_rule_yaml(_rule_data(mitre_tactics=[""]))

    def test_none_tactic_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="mitre_tactics"):
            parse_rule_yaml(_rule_data(mitre_tactics=[None]))

    def test_non_string_technique_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="mitre_techniques"):
            parse_rule_yaml(_rule_data(mitre_techniques=[42]))

    def test_empty_string_technique_rejected(self) -> None:
        with pytest.raises(RuleValidationError, match="mitre_techniques"):
            parse_rule_yaml(_rule_data(mitre_techniques=[""]))

    def test_valid_mitre_values_accepted(self) -> None:
        rule = parse_rule_yaml(
            _rule_data(
                mitre_tactics=["credential-access"],
                mitre_techniques=["T1110.001"],
            )
        )
        assert rule.mitre_tactics == ("credential-access",)
        assert rule.mitre_techniques == ("T1110.001",)


class TestDuplicateRuleDetection:
    """S-156: Duplicate rule names are warned and skipped."""

    def test_duplicate_name_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from seerflow.correlation.rule_loader import load_correlation_rules

        rule_yaml = """
name: brute-force-1
entity_type: ip
window_seconds: 600
min_sources: 1
alert_severity: 3
sources:
  - source_type: syslog
    conditions:
      message: "test.*"
    min_count: 1
"""
        (tmp_path / "rule_a.yml").write_text(rule_yaml)
        (tmp_path / "rule_b.yml").write_text(rule_yaml)
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            rules = load_correlation_rules([str(tmp_path)])
        assert len(rules) == 1
        assert rules[0].name == "brute-force-1"
        assert "Duplicate" in caplog.text

    def test_unique_names_all_loaded(self, tmp_path: Path) -> None:
        from seerflow.correlation.rule_loader import load_correlation_rules

        def _yaml(name: str) -> str:
            return f"""
name: {name}
entity_type: ip
window_seconds: 600
min_sources: 1
alert_severity: 3
sources:
  - source_type: syslog
    conditions:
      message: "test.*"
    min_count: 1
"""

        (tmp_path / "rule1.yml").write_text(_yaml("rule1"))
        (tmp_path / "rule2.yml").write_text(_yaml("rule2"))
        rules = load_correlation_rules([str(tmp_path)])
        assert len(rules) == 2
