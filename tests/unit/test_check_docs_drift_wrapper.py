"""Unit tests for ``.github/check_docs_drift.py``.

The wrapper is the seerflow-side glue that:

* Locates the canonical drift script in a checkout of ``seerflow-guide``.
* Skips silently with a clear stdout message if the script is not yet
  available (chicken-and-egg with S-180-F1 still pending).
* Forwards the script's exit status when it is available, so the CI gate
  fails the PR when drift is detected.

These tests stub the upstream script with a tiny Python file so they exercise
the real subprocess invocation path without needing a network checkout.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_PATH = REPO_ROOT / ".github" / "check_docs_drift.py"


def _load_wrapper() -> ModuleType:
    """Load the wrapper as a module from its on-disk path.

    The wrapper lives under ``.github/`` (not a Python package) so a normal
    ``import`` would fail. ``importlib.util.spec_from_file_location`` lets the
    tests target the real file the CI workflow invokes.
    """

    spec = importlib.util.spec_from_file_location(
        "_seerflow_check_docs_drift_wrapper", WRAPPER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_stub_drift_script(target: Path, *, exit_code: int, marker: Path | None) -> None:
    """Write a tiny stand-in for ``seerflow-guide/scripts/check_docs_drift.py``.

    The stub touches a marker file (so tests can prove it ran), then exits
    with the requested code. It uses only stdlib so no env setup is needed.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    marker_line = f"Path({str(marker)!r}).write_text('ran')\n" if marker is not None else ""
    target.write_text(
        f"import sys\nfrom pathlib import Path\n\n{marker_line}sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def test_wrapper_skips_when_guide_script_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Guide checkout without the script → wrapper prints a skip notice + exits 0.

    This is the deliberate fail-open behaviour while S-180-F1 is still pending.
    """

    wrapper = _load_wrapper()
    guide_dir = tmp_path / "guide"
    guide_dir.mkdir()
    report_path = tmp_path / "report.json"

    exit_code = wrapper.main(
        [
            "--guide-dir",
            str(guide_dir),
            "--report-path",
            str(report_path),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "skipping" in captured.out.lower()


def test_wrapper_invokes_guide_script_when_present(tmp_path: Path) -> None:
    """Script present + exit 0 → wrapper returns 0 and the script actually ran."""

    wrapper = _load_wrapper()
    guide_dir = tmp_path / "guide"
    docs_dir = guide_dir / "docs"
    docs_dir.mkdir(parents=True)
    marker = tmp_path / "marker.txt"
    _write_stub_drift_script(
        guide_dir / "scripts" / "check_docs_drift.py",
        exit_code=0,
        marker=marker,
    )
    report_path = tmp_path / "report.json"

    exit_code = wrapper.main(
        [
            "--guide-dir",
            str(guide_dir),
            "--report-path",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert marker.exists(), "stub script should have produced its marker file"


def test_wrapper_propagates_nonzero_exit(tmp_path: Path) -> None:
    """Stub script exits 1 → wrapper returns 1 (CI gate fails the PR)."""

    wrapper = _load_wrapper()
    guide_dir = tmp_path / "guide"
    (guide_dir / "docs").mkdir(parents=True)
    _write_stub_drift_script(
        guide_dir / "scripts" / "check_docs_drift.py",
        exit_code=1,
        marker=None,
    )
    report_path = tmp_path / "report.json"

    exit_code = wrapper.main(
        [
            "--guide-dir",
            str(guide_dir),
            "--report-path",
            str(report_path),
        ]
    )

    assert exit_code == 1


def test_wrapper_returns_124_when_canonical_script_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subprocess timeout → wrapper returns 124 (POSIX timeout convention)."""

    wrapper = _load_wrapper()
    guide_dir = tmp_path / "guide"
    (guide_dir / "docs").mkdir(parents=True)
    # The script body does not matter — we patch ``subprocess.run`` to raise.
    _write_stub_drift_script(
        guide_dir / "scripts" / "check_docs_drift.py",
        exit_code=0,
        marker=None,
    )
    report_path = tmp_path / "report.json"

    import subprocess as _subprocess

    def _raise_timeout(*_args: object, **_kwargs: object) -> None:
        raise _subprocess.TimeoutExpired(cmd="stub", timeout=1)

    monkeypatch.setattr(wrapper.subprocess, "run", _raise_timeout)

    exit_code = wrapper.main(
        [
            "--guide-dir",
            str(guide_dir),
            "--report-path",
            str(report_path),
        ]
    )

    assert exit_code == 124


def test_wrapper_runs_as_script_entry(tmp_path: Path) -> None:
    """Running the wrapper as a script (``__main__``) propagates the exit code."""

    import subprocess

    guide_dir = tmp_path / "guide"
    guide_dir.mkdir()
    report_path = tmp_path / "report.json"

    result = subprocess.run(  # noqa: S603 — controlled args, no shell
        [
            sys.executable,
            str(WRAPPER_PATH),
            "--guide-dir",
            str(guide_dir),
            "--report-path",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )

    # No script present → skip → exit 0.
    assert result.returncode == 0
    assert "skipping" in result.stdout.lower()
