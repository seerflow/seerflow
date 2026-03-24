"""Tests for CLI argument parsing."""

from __future__ import annotations

import pytest

from seerflow.cli import parse_args


class TestCLIArgs:
    def test_version_flag(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--version"])
        assert exc.value.code == 0

    def test_config_flag(self) -> None:
        args = parse_args(["--config", "/path/to/config.yaml"])
        assert args.config == "/path/to/config.yaml"

    def test_default_no_config(self) -> None:
        args = parse_args([])
        assert args.config is None

    def test_unknown_flag_exits(self) -> None:
        with pytest.raises(SystemExit) as exc:
            parse_args(["--unknown"])
        assert exc.value.code == 2
