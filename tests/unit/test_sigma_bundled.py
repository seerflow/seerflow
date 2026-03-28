"""Tests for bundled Sigma rule discovery."""

from __future__ import annotations

from pathlib import Path

from seerflow.sigma.bundled import get_bundled_rule_paths
from seerflow.sigma.engine import SigmaEngine
from tests.helpers import make_event


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
        assert len(paths) > 0, "No bundled rules found"
        for p in paths:
            assert p.exists(), f"Rule file does not exist: {p}"


class TestBundledRuleCount:
    def test_at_least_50_rules_bundled(self) -> None:
        paths = get_bundled_rule_paths()
        assert len(paths) >= 50, f"Only {len(paths)} rules bundled, need >= 50"

    def test_rules_in_expected_categories(self) -> None:
        paths = get_bundled_rule_paths()
        categories = {p.parent.name for p in paths}
        assert "linux" in categories
        assert "process" in categories
        assert "web" in categories
        assert "dns" in categories
        assert "network" in categories


class TestSigmaEngineLoadBundled:
    def test_load_bundled_populates_engine(self) -> None:
        engine = SigmaEngine()
        engine.load_bundled()
        assert engine.rule_count >= 50

    def test_load_bundled_all_rules_compile(self) -> None:
        """Every bundled rule must compile without errors."""
        engine = SigmaEngine()
        engine.load_bundled()
        paths = get_bundled_rule_paths()
        assert len(paths) >= 50, (
            f"Only {len(paths)} rules discovered — package data may be missing"
        )
        assert engine.rule_count == len(paths), (
            f"{len(paths) - engine.rule_count} rules failed to compile"
        )

    def test_bundled_rule_matches_crafted_event(self) -> None:
        """At least one bundled rule fires on a whoami event."""
        engine = SigmaEngine()
        engine.load_bundled()
        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) >= 1
