"""S-085: the built sdist + wheel are well-formed, carry correct metadata,
and install cleanly into a throwaway virtual environment.

The build is performed once per module (``uv build``) and shared by every
test. ``SEERFLOW_REQUIRE_FRONTEND=0`` so a dashboard-less checkout still
builds — the frontend gate is exercised separately by
``tests/unit/test_preflight_wheel.py``.
"""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


@pytest.fixture(scope="module")
def built_dist(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Build sdist + wheel once into a temp dir; skip if ``uv`` is absent."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("`uv` not on PATH; cannot build distributions")
    out_dir = tmp_path_factory.mktemp("dist")
    env = {**os.environ, "SEERFLOW_REQUIRE_FRONTEND": "0"}
    result = subprocess.run(  # noqa: S603 — fixed argv, resolved binary, no shell
        [uv, "build", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"uv build failed:\n{result.stderr}"

    sdists = list(out_dir.glob("seerflow-*.tar.gz"))
    wheels = list(out_dir.glob("seerflow-*-py3-none-any.whl"))
    assert len(sdists) == 1, f"expected exactly one sdist, got {sdists}"
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return {"dir": out_dir, "sdist": sdists[0], "wheel": wheels[0]}


def test_sdist_and_wheel_built(built_dist: dict[str, Path]) -> None:
    assert built_dist["sdist"].is_file()
    assert built_dist["wheel"].is_file()
    assert built_dist["sdist"].stat().st_size > 0
    assert built_dist["wheel"].stat().st_size > 0


def test_wheel_contains_package_files(built_dist: dict[str, Path]) -> None:
    with zipfile.ZipFile(built_dist["wheel"]) as zf:
        names = set(zf.namelist())
    assert "seerflow/__init__.py" in names
    assert "seerflow/py.typed" in names
    assert any(n.endswith(".dist-info/METADATA") for n in names), names


def test_wheel_metadata_renders_on_pypi(built_dist: dict[str, Path]) -> None:
    """README is carried as a text/markdown long description.

    PyPI renders the project page from ``Description-Content-Type`` +
    the message payload; asserting both here is the offline proxy for
    "README rendered correctly on PyPI".
    """
    with zipfile.ZipFile(built_dist["wheel"]) as zf:
        metadata_name = next(n for n in zf.namelist() if n.endswith(".dist-info/METADATA"))
        raw = zf.read(metadata_name).decode("utf-8")

    msg = email.message_from_string(raw)
    assert msg["Metadata-Version"], "Metadata-Version header missing"
    assert msg["Name"] == "seerflow"
    assert msg["Version"] == _pyproject_version()
    content_type = msg["Description-Content-Type"] or ""
    assert content_type.startswith("text/markdown"), content_type
    body = msg.get_payload()
    assert isinstance(body, str)
    assert "# Seerflow" in body, "README heading not carried into long description"


def test_wheel_installs_into_clean_venv(built_dist: dict[str, Path], tmp_path: Path) -> None:
    """Install the built wheel (``--no-deps``) into a fresh venv with no
    source tree on ``sys.path`` and confirm the package + console entry
    point resolve. This proves the *artifact* is installable on a clean
    machine; dependency resolution is covered by ``uv sync`` in CI.
    """
    venv_dir = tmp_path / "venv"
    subprocess.run(  # noqa: S603 — fixed argv, interpreter from sys.executable
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    py = bin_dir / ("python.exe" if os.name == "nt" else "python")

    install = subprocess.run(  # noqa: S603 — fixed argv, venv interpreter
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            str(built_dist["wheel"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, f"pip install failed:\n{install.stderr}"

    version = _pyproject_version()
    check = subprocess.run(  # noqa: S603 — fixed argv, venv interpreter
        [
            str(py),
            "-c",
            "import seerflow; print(seerflow.__version__)",
        ],
        cwd=tmp_path,  # not the repo root — no local source shadowing
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, f"import seerflow failed:\n{check.stderr}"
    assert check.stdout.strip() == version, (
        f"installed version {check.stdout.strip()!r} != {version!r}"
    )

    entry_point = bin_dir / ("seerflow.exe" if os.name == "nt" else "seerflow")
    assert entry_point.is_file(), "console entry point `seerflow` not installed"
    help_run = subprocess.run(  # noqa: S603 — fixed argv, installed entry point
        [str(entry_point), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_run.returncode == 0, f"`seerflow --help` failed:\n{help_run.stderr}"
