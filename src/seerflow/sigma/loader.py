"""Custom Sigma rule directory discovery and validation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def discover_custom_rules(dirs: Sequence[str]) -> list[Path]:
    """Validate directories and collect .yml rule file paths.

    For each directory in *dirs*:
    - Skip non-existent directories (log warning)
    - Skip non-directory paths (log warning)
    - Log info for symlinks (follows them)
    - Recurse into subdirectories
    - Collect all ``.yml`` files

    Returns a sorted list of ``Path`` objects.
    """
    paths: list[Path] = []
    for dir_str in dirs:
        dir_path = Path(dir_str)

        if dir_path.is_symlink():
            target = dir_path.resolve()
            logger.info("Following symlink in sigma rules dir: %s -> %s", dir_path, target)

        if not dir_path.exists():
            logger.warning("Custom sigma rules dir does not exist: %s — skipping", dir_path)
            continue

        if not dir_path.is_dir():
            logger.warning("Custom sigma rules path is not a directory: %s — skipping", dir_path)
            continue

        yml_files = list(dir_path.rglob("*.yml"))
        if not yml_files:
            logger.info("No .yml files in custom sigma rules dir: %s", dir_path)
        paths.extend(yml_files)

    return sorted(paths)
