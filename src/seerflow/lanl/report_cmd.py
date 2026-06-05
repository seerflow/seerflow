"""``seerflow lanl-report`` — re-render a stored LANL benchmark report (S-358, slice 4).

Reads a sidecar JSON written by the runner (``tools/run_lanl_streaming.py``) or
by any other process that calls :func:`~seerflow.lanl.report.io.write_report_json`.
Re-builds the :class:`~seerflow.lanl.report.schema.Report` against the CURRENT
baselines registry so an old sidecar can be compared against updated targets.

The stored host metadata is used as-is (``detect_host`` is NOT called here).
"""

# ruff: noqa: T201 -- print() is the CLI output mechanism.

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

EXIT_OK = 0
EXIT_FILE_NOT_FOUND = 1
EXIT_SCHEMA_ERROR = 2


def run_lanl_report(args: argparse.Namespace) -> int:
    """Entry point for ``seerflow lanl-report``.

    Args:
        args: Parsed :class:`argparse.Namespace` with ``report_json`` and
              ``json`` attributes.

    Returns:
        Process exit code: 0 on success, non-zero on error.
    """
    from seerflow.lanl.report.baselines import load_baselines
    from seerflow.lanl.report.build import build_report
    from seerflow.lanl.report.io import load_report_inputs
    from seerflow.lanl.report.render import render_json, render_table

    path = Path(args.report_json)

    if not path.exists():
        print(f"Error: report file not found: {path}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND

    try:
        inputs = load_report_inputs(path)
    except Exception as exc:
        print(f"Error: could not parse report file {path}: {exc}", file=sys.stderr)
        return EXIT_SCHEMA_ERROR

    report = build_report(
        inputs.accuracy,
        inputs.telemetry,
        load_baselines(),
        inputs.host,
    )

    if args.json:
        print(json.dumps(render_json(report), indent=2))
    else:
        print(render_table(report))

    return EXIT_OK


__all__ = ["run_lanl_report"]
