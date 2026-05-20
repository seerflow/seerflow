#!/usr/bin/env python3
"""Seerflow-side wrapper for the ``seerflow-guide`` docs-drift checker.

This script is the integration glue invoked by the ``docs-drift`` GitHub
workflow when a PR touches ``src/seerflow/config.py`` or ``src/seerflow/cli.py``.

Why a wrapper instead of a vendored copy?
-----------------------------------------

The canonical drift script lives in ``seerflow-guide/scripts/check_docs_drift.py``.
Duplicating it here would let the two copies drift apart — ironic, given the
script's purpose. Instead this wrapper:

1. Reads the path to a checkout of ``seerflow-guide`` (the CI workflow clones
   it via ``actions/checkout``).
2. Looks for the canonical script at ``<guide>/scripts/check_docs_drift.py``.
3. If absent (still true until S-180-F1 lands) → prints a *skip* message and
   exits zero. The gate fails open until the upstream contract is published.
4. If present → forwards execution as a subprocess and propagates the exit
   code so the PR fails on drift.

Local invocation:

.. code-block:: bash

    uv run python .github/check_docs_drift.py \\
        --guide-dir /path/to/seerflow-guide \\
        --report-path /tmp/drift-report.json

Why ``.github/`` rather than ``scripts/``?
    The repo's local ``.git/info/exclude`` keeps the top-level ``scripts/``
    tree out of source control (it is reserved for ad-hoc local helpers).
    ``.github/`` is committed and is the conventional location for CI glue
    that must ship with the repo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

_CANONICAL_RELATIVE_PATH = Path("scripts") / "check_docs_drift.py"
_SKIP_MESSAGE = (
    "docs-drift: canonical script not found in seerflow-guide checkout; "
    "skipping (will activate once seerflow-guide exposes scripts/check_docs_drift.py)."
)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the wrapper's argparse parser.

    Kept as a separate function so the workflow YAML test can — in principle —
    import and introspect it later without executing ``main``.
    """

    parser = argparse.ArgumentParser(
        prog="check_docs_drift",
        description="Run the seerflow-guide docs-drift script against a guide checkout.",
    )
    parser.add_argument(
        "--guide-dir",
        type=Path,
        required=True,
        help="Path to a local checkout of seerflow-guide (e.g. produced by actions/checkout).",
    )
    parser.add_argument(
        "--docs-dir",
        default="docs",
        help="Docs directory inside the guide checkout (default: docs).",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        required=True,
        help="Where the JSON drift report will be written.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the drift check wrapper.

    Returns the exit code: ``0`` for clean / skipped, ``1`` (or higher) for
    drift detected. Designed to be the body of ``raise SystemExit(main())``.
    """

    args = _build_arg_parser().parse_args(argv)

    guide_dir: Path = args.guide_dir
    docs_dir: str = args.docs_dir
    report_path: Path = args.report_path

    canonical_script = guide_dir / _CANONICAL_RELATIVE_PATH
    if not canonical_script.is_file():
        print(_SKIP_MESSAGE)  # noqa: T201 — CLI tool stdout
        return 0

    cmd = [
        sys.executable,
        str(canonical_script),
        "--docs-dir",
        str(guide_dir / docs_dir),
        "--report-path",
        str(report_path),
    ]
    completed = subprocess.run(cmd, check=False)  # noqa: S603 — args fully controlled
    return completed.returncode


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
