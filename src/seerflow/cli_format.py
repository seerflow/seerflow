"""Shared formatting helpers for CLI output."""
# ruff: noqa: T201 -- print() is the CLI output mechanism.

from __future__ import annotations

import sys

import msgspec.json


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format headers and rows into an auto-sized text table.

    Computes maximum width per column, pads with spaces, and adds
    a separator line of dashes below the header row.
    """
    if not headers:
        return ""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    lines = [fmt.format(*headers)]
    lines.append("  ".join("-" * w for w in col_widths))
    for row in rows:
        padded = row + [""] * (len(headers) - len(row))
        lines.append(fmt.format(*padded[: len(headers)]))
    return "\n".join(lines) + "\n"


def emit_doc(doc: dict[str, object], *, as_json: bool) -> None:
    """Write ``doc`` to stdout as JSON or a human two-column metric table.

    The shared emitter for CLI commands whose machine-readable output is a
    flat ``metric``/``value`` document: ``--json`` writes the msgspec-encoded
    object plus a trailing newline; otherwise a two-column table is printed.
    """
    if as_json:
        sys.stdout.write(msgspec.json.encode(doc).decode() + "\n")
        return
    rows = [[k, str(doc[k])] for k in doc]
    print(format_table(["metric", "value"], rows))


__all__ = ["emit_doc", "format_table"]
