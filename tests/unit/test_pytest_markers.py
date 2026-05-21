"""S-086 (deferred S-085 #1): pytest marker registration guard.

`--strict-markers` is set in ``pyproject.toml`` ``addopts``. Every marker the
suite uses must therefore be declared in ``[tool.pytest.ini_options].markers``
or collection fails / emits ``PytestUnknownMarkWarning``. The ``integration``
marker is applied across ~23 files under ``tests/integration/`` but was not
registered. This guard pins the registration so the warning cannot silently
return.

Parses ``pyproject.toml`` directly — fast, offline, no subprocess.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


@pytest.fixture(scope="module")
def pytest_markers() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    markers = data["tool"]["pytest"]["ini_options"]["markers"]
    assert isinstance(markers, list), "markers must be a list"
    return markers


def _marker_names(markers: list[str]) -> set[str]:
    # Markers are declared as "name: human description".
    return {entry.split(":", 1)[0].strip() for entry in markers}


def test_strict_markers_is_enabled() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--strict-markers" in addopts, (
        "this guard only matters while --strict-markers is enforced"
    )


@pytest.mark.parametrize("name", ["unit", "integration"])
def test_marker_registered(pytest_markers: list[str], name: str) -> None:
    assert name in _marker_names(pytest_markers), (
        f"pytest marker {name!r} is not registered in pyproject.toml "
        f"[tool.pytest.ini_options].markers; with --strict-markers this "
        f"breaks collection / emits PytestUnknownMarkWarning"
    )


def test_integration_marker_has_description(pytest_markers: list[str]) -> None:
    integration = next(
        (m for m in pytest_markers if m.split(":", 1)[0].strip() == "integration"),
        None,
    )
    assert integration is not None, "integration marker missing"
    assert ":" in integration and integration.split(":", 1)[1].strip(), (
        "integration marker must carry a human-readable description"
    )


def test_no_unknown_mark_warning_collecting_integration_suite() -> None:
    """Collect a representative integration test; assert no unknown-mark warning.

    Uses ``--collect-only`` so nothing is executed (fast, offline). The
    ``-p no:cacheprovider`` keeps the run hermetic.
    """
    import subprocess

    target = REPO_ROOT / "tests" / "integration" / "test_packaging_build.py"
    assert target.is_file(), f"expected integration test missing: {target}"

    result = subprocess.run(  # noqa: S603 - fixed args, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(target),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "PytestUnknownMarkWarning" not in combined, (
        "collecting the integration suite emitted PytestUnknownMarkWarning — "
        f"the `integration` marker is not registered.\n{combined}"
    )
