"""Shared formatting helpers for CLI output."""

from __future__ import annotations


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


__all__ = ["format_table"]
