"""Discovery of bundled correlation rules shipped with seerflow."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_bundled_rule_dir() -> Path:
    """Return the filesystem path to the bundled correlation rules directory.

    Uses ``importlib.resources`` for package-safe path resolution.
    Requires an unpacked (non-zipped) install — works for editable
    installs and standard wheel installs with pip's default behavior.
    """
    return Path(str(importlib.resources.files("seerflow.correlation.rules")))
