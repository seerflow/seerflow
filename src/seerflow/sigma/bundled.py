"""Discovery of bundled SigmaHQ rules shipped with the seerflow package."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_bundled_rule_paths() -> list[Path]:
    """Discover all bundled Sigma rule YAML files.

    Uses ``importlib.resources`` to find ``.yml`` files shipped under
    ``seerflow.sigma.rules`` and its subdirectories (linux/, process/,
    web/, dns/, network/).

    Returns absolute ``Path`` objects so they can be passed directly
    to ``SigmaEngine.load_rules()``.
    """
    rules_pkg = importlib.resources.files("seerflow.sigma.rules")
    paths: list[Path] = []
    for item in rules_pkg.iterdir():
        item_path = Path(str(item))
        if item_path.is_dir():
            for yml in item_path.glob("*.yml"):
                paths.append(yml)
        elif item_path.suffix == ".yml":
            paths.append(item_path)
    return sorted(paths)
