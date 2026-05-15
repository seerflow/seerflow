"""S-085: version consistency across the three release-please-managed sources.

release-please writes the version into ``pyproject.toml``,
``src/seerflow/__init__.py`` (via ``extra-files``), and
``.release-please-manifest.json`` in a single release commit, then tags
``vX.Y.Z``. The published PyPI version is therefore "from the git tag" iff
these three sources always agree. This test guards that invariant so a manual
edit or a drift can never publish a tag/version mismatch.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# PEP 440 release segment with optional pre/post/dev — kept stdlib so the
# unit suite has no extra dependency.
_PEP440 = re.compile(
    r"^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*"
    r"((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?$"
)


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def _init_version() -> str:
    src = (REPO_ROOT / "src" / "seerflow" / "__init__.py").read_text(encoding="utf-8")
    module = ast.parse(src)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__version__"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    return node.value.value
    raise AssertionError("__version__ string assignment not found in __init__.py")


def _manifest_version() -> str:
    data = json.loads((REPO_ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    version = data["."]
    assert isinstance(version, str)
    return version


def test_three_version_sources_agree() -> None:
    pyproject = _pyproject_version()
    init = _init_version()
    manifest = _manifest_version()
    assert pyproject == init == manifest, (
        "version drift: "
        f"pyproject.toml={pyproject!r}, __init__.__version__={init!r}, "
        f".release-please-manifest.json={manifest!r}"
    )


def test_version_is_pep440() -> None:
    version = _pyproject_version()
    assert _PEP440.match(version), f"{version!r} is not a valid PEP 440 version"
