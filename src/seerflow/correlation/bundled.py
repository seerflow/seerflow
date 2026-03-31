"""Discovery of bundled correlation rules shipped with seerflow."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_bundled_rule_dir() -> Path:
    """Return the filesystem path to the bundled correlation rules directory.

    Uses ``importlib.resources`` so that the path resolves correctly for
    both editable installs and wheel installs.
    """
    return Path(str(importlib.resources.files("seerflow.correlation.rules")))
