"""Tests for discover_custom_rules upload_dir extension (S-151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from seerflow.sigma.loader import discover_custom_rules

if TYPE_CHECKING:
    from pathlib import Path


def test_upload_dir_files_are_returned(tmp_path: Path) -> None:
    upload = tmp_path / "uploads"
    upload.mkdir()
    (upload / "x.yml").write_text("title: X\n")
    paths = discover_custom_rules([], upload_dir=upload)
    assert any(p.name == "x.yml" for p in paths)


def test_upload_dir_none_returns_dirs_only(tmp_path: Path) -> None:
    paths = discover_custom_rules([], upload_dir=None)
    assert paths == []


def test_upload_dir_combined_with_dirs(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "a.yml").write_text("title: A\n")

    upload = tmp_path / "uploads"
    upload.mkdir()
    (upload / "b.yml").write_text("title: B\n")

    paths = discover_custom_rules([str(rules_dir)], upload_dir=upload)
    names = sorted(p.name for p in paths)
    assert names == ["a.yml", "b.yml"]


def test_upload_dir_missing_is_silently_skipped(tmp_path: Path) -> None:
    paths = discover_custom_rules([], upload_dir=tmp_path / "does-not-exist")
    assert paths == []
