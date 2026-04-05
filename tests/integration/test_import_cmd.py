"""Integration tests for batch log import (S-160: moved from unit tests)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class TestRunImport:
    @pytest.mark.asyncio
    async def test_imports_plain_text_file(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import run_import

        log_file = tmp_path / "test.log"
        log_file.write_text("Login from 10.0.1.1\nLogout user=admin\n")

        stats = await run_import(
            paths=[str(log_file)],
            db_path=str(tmp_path / "test.db"),
        )
        assert stats["files_processed"] == 1
        assert stats["lines_read"] == 2
        assert stats["lines_read"] >= 2

    @pytest.mark.asyncio
    async def test_skips_binary_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from seerflow.import_cmd import run_import

        bin_file = tmp_path / "binary.bin"
        bin_file.write_bytes(b"ELF\x00\x01" + b"\x00" * 100)

        with caplog.at_level(logging.WARNING, logger="seerflow"):
            stats = await run_import(
                paths=[str(bin_file)],
                db_path=str(tmp_path / "test.db"),
            )
        assert stats["files_processed"] == 0
        assert "binary" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_imports_gzip_file(self, tmp_path: Path) -> None:
        import gzip as _gzip

        from seerflow.import_cmd import run_import

        gz_file = tmp_path / "test.log.gz"
        with _gzip.open(gz_file, "wt") as f:
            f.write("Compressed line 1\nCompressed line 2\n")

        stats = await run_import(
            paths=[str(gz_file)],
            db_path=str(tmp_path / "test.db"),
        )
        assert stats["files_processed"] == 1
        assert stats["lines_read"] == 2

    @pytest.mark.asyncio
    async def test_empty_paths_returns_zero_stats(self, tmp_path: Path) -> None:
        from seerflow.import_cmd import run_import

        stats = await run_import(
            paths=[],
            db_path=str(tmp_path / "test.db"),
        )
        assert stats["files_processed"] == 0
        assert stats["lines_read"] == 0
