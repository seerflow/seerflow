"""Tests for bundled Sigma rule discovery."""

from __future__ import annotations

from pathlib import Path

from seerflow.sigma.bundled import get_bundled_rule_paths


class TestBundledRuleDiscovery:
    def test_returns_list_of_paths(self) -> None:
        paths = get_bundled_rule_paths()
        assert isinstance(paths, list)
        assert all(isinstance(p, Path) for p in paths)

    def test_all_paths_are_yml_files(self) -> None:
        paths = get_bundled_rule_paths()
        for p in paths:
            assert p.suffix == ".yml", f"Non-YAML file found: {p}"

    def test_all_paths_exist(self) -> None:
        paths = get_bundled_rule_paths()
        for p in paths:
            assert p.exists(), f"Rule file does not exist: {p}"
