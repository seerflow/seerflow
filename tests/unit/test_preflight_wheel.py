"""Preflight check: refuse dashboard-less wheels when gated (S-057)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "preflight_wheel.py"
DIST_INDEX = REPO_ROOT / "src" / "seerflow" / "web" / "dist" / "index.html"


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — fixed argv, no shell, test-local
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_noop_when_not_required() -> None:
    result = _run({"SEERFLOW_REQUIRE_FRONTEND": "0"})
    assert result.returncode == 0, result.stderr


def test_preflight_passes_when_required_and_present() -> None:
    if not DIST_INDEX.is_file():
        pytest.skip("frontend not built; run scripts/build_frontend.sh")
    result = _run({"SEERFLOW_REQUIRE_FRONTEND": "1"})
    assert result.returncode == 0, result.stderr


def test_preflight_fails_loudly_when_required_and_missing(
    tmp_path: Path,
) -> None:
    # Invoke a copy of the script pointed at an empty tree so the
    # assertion is deterministic regardless of the checkout's build state.
    stub_root = tmp_path / "repo"
    (stub_root / "src" / "seerflow" / "web" / "dist").mkdir(parents=True)
    copy = stub_root / "preflight_wheel.py"
    copy.write_bytes(SCRIPT.read_bytes())
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(copy)],
        cwd=stub_root,
        env={**os.environ, "SEERFLOW_REQUIRE_FRONTEND": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "frontend build missing" in result.stderr
