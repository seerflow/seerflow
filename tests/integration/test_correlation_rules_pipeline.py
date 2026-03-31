"""Integration test for correlation rule loading at pipeline startup."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


class TestCorrelationRulePipelineIntegration:
    def test_load_rules_from_config_dirs(self, tmp_path: Path) -> None:
        """Rules are loaded from config.correlation.rule_dirs at startup."""
        from seerflow.correlation.rule_loader import load_correlation_rules

        rule_dir = tmp_path / "rules"
        rule_dir.mkdir()
        (rule_dir / "test_rule.yml").write_text(
            """
name: integration_test_rule
entity_type: user
window_seconds: 600
min_sources: 1
alert_severity: 3
sources:
  - source_type: syslog
    conditions:
      message: "sudo.*"
    min_count: 1
"""
        )
        rules = load_correlation_rules([str(rule_dir)])
        assert len(rules) == 1
        assert rules[0].name == "integration_test_rule"
        assert rules[0].entity_type == "user"
        assert len(rules[0].sources) == 1
