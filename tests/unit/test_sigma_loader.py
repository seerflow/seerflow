"""Tests for custom Sigma rule directory discovery and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.sigma.engine import SigmaEngine
from seerflow.sigma.loader import discover_custom_rules
from tests.helpers import make_event

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestDiscoverCustomRules:
    def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent directory is skipped with warning."""
        result = discover_custom_rules([str(tmp_path / "nonexistent")])
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        """Empty directory produces no rules."""
        result = discover_custom_rules([str(tmp_path)])
        assert result == []

    def test_valid_dir_returns_yml_paths(self, tmp_path: Path) -> None:
        """Directory with .yml files returns their paths."""
        rule = tmp_path / "test_rule.yml"
        rule.write_text(
            "title: Test\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: value\n  condition: sel\nlevel: medium\nstatus: test\n"
        )
        result = discover_custom_rules([str(tmp_path)])
        assert len(result) == 1
        assert result[0].name == "test_rule.yml"

    def test_non_yml_files_ignored(self, tmp_path: Path) -> None:
        """Non-.yml files in the directory are ignored."""
        (tmp_path / "readme.txt").write_text("not a rule")
        (tmp_path / "notes.md").write_text("not a rule")
        (tmp_path / "rule.yml").write_text(
            "title: Test\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: value\n  condition: sel\nlevel: medium\nstatus: test\n"
        )
        result = discover_custom_rules([str(tmp_path)])
        assert len(result) == 1

    def test_multiple_dirs(self, tmp_path: Path) -> None:
        """Rules from multiple directories are combined."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "rule1.yml").write_text(
            "title: Rule1\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: v\n  condition: sel\nlevel: low\nstatus: test\n"
        )
        (dir2 / "rule2.yml").write_text(
            "title: Rule2\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: v\n  condition: sel\nlevel: low\nstatus: test\n"
        )
        result = discover_custom_rules([str(dir1), str(dir2)])
        assert len(result) == 2

    def test_symlink_followed_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Symlinks in rule directories are followed with a log warning."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "rule.yml").write_text(
            "title: Test\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: v\n  condition: sel\nlevel: low\nstatus: test\n"
        )
        link = tmp_path / "linked"
        link.symlink_to(real_dir)
        with caplog.at_level("INFO", logger="seerflow.sigma.loader"):
            result = discover_custom_rules([str(link)])
        assert len(result) == 1
        assert "symlink" in caplog.text.lower() or "Following symlink" in caplog.text

    def test_subdirs_recursed(self, tmp_path: Path) -> None:
        """Rules in subdirectories within the custom dir are discovered."""
        subdir = tmp_path / "linux"
        subdir.mkdir()
        (subdir / "rule.yml").write_text(
            "title: Test\nlogsource:\n  category: test\ndetection:\n"
            "  sel:\n    field: v\n  condition: sel\nlevel: low\nstatus: test\n"
        )
        result = discover_custom_rules([str(tmp_path)])
        assert len(result) == 1

    def test_empty_dirs_list(self) -> None:
        """Empty dirs list returns empty result."""
        result = discover_custom_rules([])
        assert result == []


class TestSigmaEngineLoadCustom:
    def test_load_custom_with_valid_dir(self, tmp_path: Path) -> None:
        """Custom rules are loaded into the engine."""
        rule = tmp_path / "custom_rule.yml"
        rule.write_text(
            "title: Custom Test Rule\n"
            "status: test\n"
            "logsource:\n"
            "  category: process_creation\n"
            "  product: linux\n"
            "detection:\n"
            "  sel:\n"
            "    CommandLine|contains: custom-payload\n"
            "  condition: sel\n"
            "level: high\n"
        )
        engine = SigmaEngine()
        engine.load_custom([str(tmp_path)])
        assert engine.rule_count == 1

    def test_load_custom_with_nonexistent_dir(self) -> None:
        """Non-existent directory doesn't crash the engine."""
        engine = SigmaEngine()
        engine.load_custom(["/nonexistent/path"])
        assert engine.rule_count == 0

    def test_bundled_plus_custom(self, tmp_path: Path) -> None:
        """Custom rules load alongside bundled rules."""
        rule = tmp_path / "extra.yml"
        rule.write_text(
            "title: Extra Rule\n"
            "status: test\n"
            "logsource:\n"
            "  category: test\n"
            "detection:\n"
            "  sel:\n"
            "    CommandLine|contains: extra-test\n"
            "  condition: sel\n"
            "level: low\n"
        )
        engine = SigmaEngine()
        engine.load_bundled()
        bundled_count = engine.rule_count
        engine.load_custom([str(tmp_path)])
        assert engine.rule_count == bundled_count + 1

    def test_custom_rule_fires_on_event(self, tmp_path: Path) -> None:
        """A custom rule can match and produce an alert."""
        rule = tmp_path / "detect_foobar.yml"
        rule.write_text(
            "title: Detect Foobar\n"
            "status: test\n"
            "logsource:\n"
            "  category: process_creation\n"
            "  product: linux\n"
            "detection:\n"
            "  sel:\n"
            "    CommandLine|contains: foobar\n"
            "  condition: sel\n"
            "level: critical\n"
        )
        engine = SigmaEngine()
        engine.load_custom([str(tmp_path)])
        event = make_event(
            message="bash -c foobar",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "Detect Foobar"
