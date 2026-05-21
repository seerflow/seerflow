"""Re-runnable CLI driver for the EPIC-DOC retro backfill (S-180-F3).

Loads a JSON file of pre-fetched Linear issue payloads (one entry per child
story) and writes the markdown + CSV outputs. Keeping the Linear MCP fetch
outside of this driver means CI never needs Linear credentials — the JSON
payload is committed alongside the markdown for reproducibility.

Usage:

    uv run python -m documents.seerflow-guide-staging.retro_backfill.cli \
        --issues path/to/issues.json \
        --plan path/to/plan.json \
        --markdown documents/.../guide/retros/epic-doc-2026-04.md \
        --csv documents/.../guide/retros/epic-doc-2026-04-actuals.csv

``issues.json`` shape:
    {"SEE-174": {<get_issue payload>}, "SEE-175": {...}, ...}

``plan.json`` shape (the static "what was planned" for each story-id):
    [{"story_id": "S-139A", "linear_id": "SEE-174", "planned_pts": 3}, ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import backfill as _backfill

if TYPE_CHECKING:
    from collections.abc import Iterable


def run(
    *,
    plan: Iterable[dict[str, Any]],
    issues: dict[str, dict[str, Any]],
    markdown_path: Path,
    csv_path: Path,
) -> None:
    """Apply the backfill to ``markdown_path`` + write ``csv_path``.

    ``plan`` is the planned-state metadata (story_id, linear_id, planned_pts).
    ``issues`` maps Linear-ID -> issue payload dict (already fetched).
    """

    rows: list[dict[str, Any]] = []
    for entry in plan:
        story_id = entry["story_id"]
        linear_id = entry.get("linear_id")
        planned_pts = entry.get("planned_pts")
        issue = issues.get(linear_id) if linear_id else None
        csv_row = _backfill.build_csv_row(story_id, linear_id, issue, planned_pts=planned_pts)
        csv_row["actual_cell"] = _backfill.render_actual_cell(issue)
        rows.append(csv_row)

    _backfill.write_csv(rows, csv_path)
    md_text = markdown_path.read_text(encoding="utf-8")
    updated = _backfill.update_markdown_table(md_text, rows)
    markdown_path.write_text(updated, encoding="utf-8")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    issues = json.loads(args.issues.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    run(plan=plan, issues=issues, markdown_path=args.markdown, csv_path=args.csv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
