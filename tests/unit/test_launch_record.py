"""Unit tests for the asciinema command builder (S-090)."""

from __future__ import annotations

from unittest.mock import patch

from seerflow.launch.record import build_asciinema_command


def test_build_default_command() -> None:
    cmd = build_asciinema_command("demo.cast")
    assert cmd == [
        "asciinema",
        "rec",
        "--overwrite",
        "--command",
        "python -m seerflow.launch.demo",
        "demo.cast",
    ]


def test_build_custom_demo_cmd() -> None:
    cmd = build_asciinema_command("out.cast", demo_cmd="echo hi")
    assert cmd[4] == "echo hi"
    assert cmd[-1] == "out.cast"


def test_main_prints_command(capsys) -> None:
    from seerflow.launch.record import main

    assert main(["demo.cast"]) == 0
    assert "asciinema rec" in capsys.readouterr().out


def test_main_exec_runs_subprocess() -> None:
    from seerflow.launch.record import main

    with patch("seerflow.launch.record.subprocess.run") as run:
        run.return_value.returncode = 0
        assert main(["demo.cast", "--exec"]) == 0
        run.assert_called_once()
        assert run.call_args[0][0][0] == "asciinema"
