"""Discovery of bundled SigmaHQ rules shipped with the seerflow package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_bundled_rule_paths() -> list[Path]:
    """Discover all bundled Sigma rule YAML files.

    Uses ``importlib.resources`` to find ``.yml`` files shipped under
    ``seerflow.sigma.rules`` and its subdirectories (linux/, process/,
    web/, dns/, network/).

    Returns ``Path`` objects. For standard pip installs (including wheels),
    the package is extracted to site-packages as real files on disk.
    """
    rules_pkg = importlib.resources.files("seerflow.sigma.rules")
    paths: list[Path] = []
    for item in rules_pkg.iterdir():
        if not item.is_dir() or item.name.startswith("_"):
            continue
        for sub in item.iterdir():
            if sub.is_file() and sub.name.endswith(".yml"):
                paths.append(Path(str(sub)))
    return sorted(paths)
