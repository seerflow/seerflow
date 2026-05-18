"""Unit tests for ``seerflow analyze`` (S-303, FR-070)."""

from __future__ import annotations

import argparse
import io
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from seerflow.cli import parse_args


class TestAnalyzeArgparse:
    def test_single_file(self) -> None:
        args = parse_args(["analyze", "/var/log/auth.log"])
        assert args.command == "analyze"
        assert args.paths == ["/var/log/auth.log"]
        assert args.persist is False
        assert args.output is None
        assert args.db is None

    def test_stdin_token(self) -> None:
        args = parse_args(["analyze", "-"])
        assert args.paths == ["-"]

    def test_persist_and_output_and_db(self) -> None:
        args = parse_args(
            ["analyze", "a.log", "b.log", "--persist", "--output", "out.ndjson", "--db", "x.db"]
        )
        assert args.paths == ["a.log", "b.log"]
        assert args.persist is True
        assert args.output == "out.ndjson"
        assert args.db == "x.db"

    def test_no_persist_explicit(self) -> None:
        args = parse_args(["analyze", "a.log", "--no-persist"])
        assert args.persist is False


class TestIterRawEvents:
    def test_yields_events_from_file(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        f = tmp_path / "a.log"
        f.write_text("line one\nline two\n\n")
        events = list(_iter_raw_events([str(f)], stdin=io.StringIO("")))
        assert [e.data for e in events] == [b"line one", b"line two"]
        assert all(e.source_type == "analyze" for e in events)

    def test_reads_stdin_on_dash(self, tmp_path: Path) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        events = list(_iter_raw_events(["-"], stdin=io.StringIO("piped a\npiped b\n")))
        assert [e.data for e in events] == [b"piped a", b"piped b"]

    def test_skips_binary_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        b = tmp_path / "x.bin"
        b.write_bytes(b"ELF\x00\x01" + b"\x00" * 50)
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            events = list(_iter_raw_events([str(b)], stdin=io.StringIO("")))
        assert events == []
        assert "binary" in caplog.text.lower()

    def test_skips_unreadable_file(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from seerflow.analyze_cmd import _iter_raw_events

        missing = tmp_path / "nope.log"
        with caplog.at_level(logging.WARNING, logger="seerflow"):
            events = list(_iter_raw_events([str(missing)], stdin=io.StringIO("")))
        assert events == []
