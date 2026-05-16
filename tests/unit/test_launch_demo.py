"""Smoke tests for the launch demo (S-090)."""

from __future__ import annotations

from seerflow.launch.demo import run_demo


def test_run_demo_exits_zero_and_narrates(capsys) -> None:
    rc = run_demo(count=80, seed=7)
    out = capsys.readouterr().out
    assert rc == 0
    assert "== Seerflow demo ==" in out
    assert "[1/4] boot" in out
    assert "[2/4] ingest" in out
    assert "[3/4] detect" in out
    assert "[4/4] alerts" in out


def test_run_demo_main_returns_zero(capsys) -> None:
    from seerflow.launch.demo import main

    assert main(["--count", "60"]) == 0
    assert "== Seerflow demo ==" in capsys.readouterr().out
