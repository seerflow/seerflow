"""Tests for bundled correlation rule discovery and validation."""

from __future__ import annotations

from pathlib import Path


class TestGetBundledRuleDir:
    def test_returns_path_to_rules_directory(self) -> None:
        from seerflow.correlation.bundled import get_bundled_rule_dir

        rule_dir = get_bundled_rule_dir()
        assert isinstance(rule_dir, Path)
        assert rule_dir.is_dir()

    def test_directory_contains_yml_files(self) -> None:
        from seerflow.correlation.bundled import get_bundled_rule_dir

        rule_dir = get_bundled_rule_dir()
        yml_files = list(rule_dir.glob("*.yml"))
        assert len(yml_files) == 5
