"""Pure helpers backing the EPIC-DOC retrospective backfill (S-180-F3).

The helpers operate on already-fetched Linear issue dicts (the shape returned
by ``mcp__plugin_linear_linear__get_issue``). Splitting the fetch from the
transform keeps the unit tests deterministic — no MCP, no network.

Output:

* ``compute_cycle_days`` — calendar-day cycle time from ``startedAt`` and
  ``completedAt``.
* ``format_delta`` — signed point delta between planned and actual.
* ``render_actual_cell`` — the human-readable string injected into the
  ``Actual pts`` markdown column.
* ``build_csv_row`` — flat dict per story for ``write_csv``.
* ``write_csv`` — stable column ordering, ``None`` serialised as empty string.
* ``update_markdown_table`` — replaces ``TBD`` cells in the per-story table
  by ``story_id`` match. Idempotent and safe to re-run.
"""

from __future__ import annotations

import csv
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "CSV_COLUMNS",
    "build_csv_row",
    "compute_cycle_days",
    "format_delta",
    "render_actual_cell",
    "update_markdown_table",
    "write_csv",
]


# ---------------------------------------------------------------------------
# CSV schema
# ---------------------------------------------------------------------------


CSV_COLUMNS: tuple[str, ...] = (
    "story_id",
    "linear_id",
    "planned_pts",
    "actual_pts",
    "started_at",
    "completed_at",
    "cycle_days",
    "delta",
    "status",
)

# Cycle-day precision used in the CSV — 4 decimals gives sub-second accuracy
# without bloating the file with float-repr noise.
_CYCLE_DAYS_PRECISION = 4


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_iso(timestamp: str | None) -> datetime | None:
    """Parse a Linear-style ISO-8601 timestamp ("...Z") to ``datetime``.

    Returns ``None`` for missing or malformed input — never raises.
    """

    if not timestamp:
        return None
    # ``fromisoformat`` accepts ``+00:00`` but not ``Z``; normalise.
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_cycle_days(started_at: str | None, completed_at: str | None) -> float | None:
    """Return the cycle time in fractional days, or ``None``.

    Returns ``None`` when either timestamp is missing or when
    ``completed_at`` precedes ``started_at`` (defensive guard against bad
    data — a negative cycle time would corrupt downstream stats).
    """

    start = _parse_iso(started_at)
    end = _parse_iso(completed_at)
    if start is None or end is None:
        return None
    delta = end - start
    if delta.total_seconds() < 0:
        return None
    return delta.total_seconds() / 86_400.0


def format_delta(planned: int | None, actual: int | None) -> str:
    """Return a signed delta string, or ``"n/a"`` when inputs are missing."""

    if planned is None or actual is None:
        return "n/a"
    diff = actual - planned
    sign = "+" if diff >= 0 else "-"
    return f"{sign}{abs(diff)}"


def _format_cycle(days: float | None) -> str:
    if days is None:
        return "? days"
    if days < 1:
        return "<1 day"
    rounded = round(days)
    return f"{rounded} day" if rounded == 1 else f"{rounded} days"


def _extract_estimate(issue: dict[str, Any] | None) -> int | None:
    if not issue:
        return None
    estimate = issue.get("estimate")
    if not estimate:
        return None
    value = estimate.get("value")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def render_actual_cell(issue: dict[str, Any] | None) -> str:
    """Render the per-story ``Actual pts`` table cell.

    Examples: ``"3 pts (<1 day)"``, ``"5 pts (3 days)"``, ``"n/a"``,
    ``"? pts (1 day)"`` when the estimate is missing but timestamps survive.
    """

    if issue is None:
        return "n/a"
    pts = _extract_estimate(issue)
    pts_label = f"{pts} pts" if pts is not None else "? pts"
    days = compute_cycle_days(issue.get("startedAt"), issue.get("completedAt"))
    return f"{pts_label} ({_format_cycle(days)})"


def build_csv_row(
    story_id: str,
    linear_id: str | None,
    issue: dict[str, Any] | None,
    *,
    planned_pts: int | None,
) -> dict[str, Any]:
    """Build a single CSV row dict.

    A row's ``status`` is ``"missing"`` when ``issue is None``. Partial data
    (e.g. missing estimate) still produces ``status="ok"`` so the row is
    rendered with explicit ``?`` markers — the retrospective is more honest
    when it shows which fields the Linear API actually returned.
    """

    if issue is None:
        return {
            "story_id": story_id,
            "linear_id": linear_id or "",
            "planned_pts": planned_pts,
            "actual_pts": None,
            "started_at": None,
            "completed_at": None,
            "cycle_days": None,
            "delta": "n/a",
            "status": "missing",
        }

    actual_pts = _extract_estimate(issue)
    started_at = issue.get("startedAt")
    completed_at = issue.get("completedAt")
    return {
        "story_id": story_id,
        "linear_id": linear_id or "",
        "planned_pts": planned_pts,
        "actual_pts": actual_pts,
        "started_at": started_at,
        "completed_at": completed_at,
        "cycle_days": compute_cycle_days(started_at, completed_at),
        "delta": format_delta(planned_pts, actual_pts),
        "status": "ok",
    }


def write_csv(rows: Iterable[dict[str, Any]], dest: Path) -> None:
    """Write rows to ``dest`` with stable column ordering.

    Side effect: creates ``dest.parent`` if it does not exist. ``None`` values
    are serialised as empty strings (otherwise ``DictWriter`` would emit the
    literal ``"None"``). ``cycle_days`` is rounded to
    :data:`_CYCLE_DAYS_PRECISION` decimals to keep the CSV diff-friendly.
    """

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _serialize_cell(col, row.get(col)) for col in CSV_COLUMNS})


def _serialize_cell(column: str, value: Any) -> Any:
    """Convert a row value to its CSV-friendly representation."""

    if value is None:
        return ""
    if column == "cycle_days" and isinstance(value, float):
        return round(value, _CYCLE_DAYS_PRECISION)
    return value


# ---------------------------------------------------------------------------
# Markdown table updater
# ---------------------------------------------------------------------------


def update_markdown_table(md_text: str, rows: Iterable[dict[str, Any]]) -> str:
    """Replace ``TBD`` cells in the per-story table.

    Each row in ``rows`` must carry ``story_id`` and ``actual_cell``. When the
    row's ``status`` is ``"missing"`` the cell text is rendered with a footnote
    marker ``[^missing-linear]`` (the markdown file already explains the
    footnote in S-180-F3's update pass — see CLI driver).

    The updater is idempotent: running it twice yields the same output as
    once. It matches by ``story_id`` (column 1) and rewrites column 2
    (``linear_id``) when the row supplies a non-empty ID — so the original
    em-dash placeholders get filled in.
    """

    row_index: dict[str, dict[str, Any]] = {
        row["story_id"]: row for row in rows if row.get("story_id")
    }
    if not row_index:
        return md_text

    out_lines: list[str] = []
    for line in md_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        replacement = _try_replace_row(stripped, row_index)
        if replacement is None:
            out_lines.append(line)
            continue
        # Preserve the original line terminator so the file's trailing
        # newline structure is untouched.
        terminator = line[len(stripped) :]
        out_lines.append(replacement + terminator)
    return "".join(out_lines)


def _try_replace_row(line: str, row_index: dict[str, dict[str, Any]]) -> str | None:
    if not line.startswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if len(cells) < 6:
        return None
    story_id = cells[0]
    if story_id not in row_index:
        return None
    row = row_index[story_id]
    actual_cell = row.get("actual_cell", "n/a")
    status = row.get("status", "ok")
    linear_id_new = row.get("linear_id") or cells[1]  # keep existing if missing

    if status == "missing" and not row.get("linear_id"):
        actual_cell = f"{actual_cell} [^missing-linear]"
        linear_id_new = cells[1]  # leave em-dash untouched

    # Rebuild the line preserving the column count (6 cells).
    new_cells = [
        story_id,
        linear_id_new,
        cells[2],
        cells[3],
        cells[4],
        actual_cell,
    ]
    return "| " + " | ".join(new_cells) + " |"
