"""Unit tests for ``seerflow analyze`` (S-303, FR-070)."""

from __future__ import annotations

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
