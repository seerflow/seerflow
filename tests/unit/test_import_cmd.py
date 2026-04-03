"""Tests for batch log import utilities."""

from __future__ import annotations

import bz2
import gzip
import lzma
import logging
from pathlib import Path

import pytest


class TestOpenLog:
    def test_plain_text_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import open_log

        f = tmp_path / "test.log"
        f.write_text("line1\nline2\n")
        with open_log(f) as fh:
            lines = fh.readlines()
        assert lines == ["line1\n", "line2\n"]

    def test_gzip_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import open_log

        f = tmp_path / "test.log.gz"
        with gzip.open(f, "wt") as gz:
            gz.write("gzline1\ngzline2\n")
        with open_log(f) as fh:
            lines = fh.readlines()
        assert lines == ["gzline1\n", "gzline2\n"]

    def test_bz2_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import open_log

        f = tmp_path / "test.log.bz2"
        with bz2.open(f, "wt") as bz:
            bz.write("bzline1\n")
        with open_log(f) as fh:
            lines = fh.readlines()
        assert lines == ["bzline1\n"]

    def test_xz_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import open_log

        f = tmp_path / "test.log.xz"
        with lzma.open(f, "wt") as xz:
            xz.write("xzline1\n")
        with open_log(f) as fh:
            lines = fh.readlines()
        assert lines == ["xzline1\n"]

    def test_unknown_extension_opens_as_text(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import open_log

        f = tmp_path / "test.dat"
        f.write_text("data\n")
        with open_log(f) as fh:
            assert fh.readline() == "data\n"


class TestIsBinary:
    def test_text_file_not_binary(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import is_binary

        f = tmp_path / "text.log"
        f.write_text("hello world\n")
        assert is_binary(f) is False

    def test_binary_file_detected(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import is_binary

        f = tmp_path / "binary.bin"
        f.write_bytes(b"ELF\x00\x01\x02\x03" + b"\x00" * 100)
        assert is_binary(f) is True

    def test_empty_file_not_binary(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import is_binary

        f = tmp_path / "empty.log"
        f.write_bytes(b"")
        assert is_binary(f) is False

    def test_gzip_file_not_checked_as_binary(self, tmp_path: Path) -> None:
        """Compressed files should not be checked for binary content."""
        from seerflow.import_cmd import is_binary

        f = tmp_path / "test.log.gz"
        with gzip.open(f, "wt") as gz:
            gz.write("text\n")
        # .gz files have binary content but are not "binary log files"
        assert is_binary(f) is False


class TestExpandPaths:
    def test_single_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import expand_paths

        f = tmp_path / "test.log"
        f.write_text("data\n")
        result = expand_paths([str(f)])
        assert result == [f]

    def test_glob_pattern(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import expand_paths

        (tmp_path / "a.log").write_text("a\n")
        (tmp_path / "b.log").write_text("b\n")
        (tmp_path / "c.txt").write_text("c\n")
        result = expand_paths([str(tmp_path / "*.log")])
        assert len(result) == 2
        assert all(p.suffix == ".log" for p in result)

    def test_nonexistent_path_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from seerflow.import_cmd import expand_paths

        with caplog.at_level(logging.WARNING, logger="seerflow"):
            result = expand_paths([str(tmp_path / "nonexistent.log")])
        assert result == []
        assert "No files matched" in caplog.text

    def test_directory_skipped(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import expand_paths

        result = expand_paths([str(tmp_path)])
        assert result == []

    def test_dedup_preserves_order(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import expand_paths

        f = tmp_path / "test.log"
        f.write_text("data\n")
        result = expand_paths([str(f), str(f)])
        assert len(result) == 1
