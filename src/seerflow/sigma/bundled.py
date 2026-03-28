"""Discovery of bundled SigmaHQ rules shipped with the seerflow package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable


def _collect_yml(item: Traversable, paths: list[Path]) -> None:
    """Recursively collect .yml files from a Traversable tree."""
    if item.is_file() and item.name.endswith(".yml"):
        paths.append(Path(str(item)))
    elif item.is_dir() and not item.name.startswith("_"):
        for child in item.iterdir():
            _collect_yml(child, paths)


def get_bundled_rule_paths() -> list[Path]:
    """Discover all bundled Sigma rule YAML files.

    Uses ``importlib.resources`` to find ``.yml`` files shipped under
    ``seerflow.sigma.rules`` and its subdirectories (linux/, process/,
    web/, dns/, network/). Recurses into nested subdirectories.

    Returns ``Path`` objects. For standard pip installs (including wheels),
    the package is extracted to site-packages as real files on disk.
    """
    rules_pkg = importlib.resources.files("seerflow.sigma.rules")
    paths: list[Path] = []
    for item in rules_pkg.iterdir():
        _collect_yml(item, paths)
    return sorted(paths)
