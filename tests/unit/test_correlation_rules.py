"""Tests for correlation rule YAML parsing and validation."""

from __future__ import annotations

import pytest

from seerflow.correlation.rule_loader import RuleValidationError, parse_rule_yaml

VALID_RULE: dict[str, object] = {
    "name": "ssh_brute_force",
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
        assert rule.name == "ssh_brute_force"
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
