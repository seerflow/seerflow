"""Tests for the EPIC-DOC retrospective backfill helpers (S-180-F3).

The helpers live outside ``src/seerflow/`` (under
``documents/seerflow-guide-staging/retro_backfill/``) because they are a
guide-staging utility, not part of the runtime package — same pattern as
``drift_check``. They are loaded via :mod:`importlib` so the test suite does
not require the staging tree to sit on ``sys.path``.

The helpers are pure functions over already-fetched Linear issue dicts; the
MCP fetch itself stays in the agent session, never in CI.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_PATH = (
    _REPO_ROOT / "documents" / "seerflow-guide-staging" / "retro_backfill" / "backfill.py"
)
_spec = importlib.util.spec_from_file_location("retro_backfill_backfill", _HELPER_PATH)
assert _spec and _spec.loader, "could not load retro_backfill.backfill module spec"
backfill = importlib.util.module_from_spec(_spec)
sys.modules["retro_backfill_backfill"] = backfill
_spec.loader.exec_module(backfill)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_issue(
    *,
    started_at: str | None = "2026-04-08T00:05:46.207Z",
    completed_at: str | None = "2026-04-08T01:28:14.880Z",
    estimate_value: int | None = 3,
) -> dict[str, Any]:
    """Build a Linear-issue-shaped dict for tests.

    Only the keys the helpers read are populated.
    """

    return {
        "startedAt": started_at,
        "completedAt": completed_at,
        "estimate": (
            None
            if estimate_value is None
            else {"value": estimate_value, "name": f"{estimate_value} Points"}
        ),
    }


# ---------------------------------------------------------------------------
# compute_cycle_days
# ---------------------------------------------------------------------------


class TestComputeCycleDays:
    def test_returns_fractional_days_for_intra_day_cycle(self) -> None:
        # ~1h22m → ~0.057 days
        days = backfill.compute_cycle_days("2026-04-08T00:05:46.207Z", "2026-04-08T01:28:14.880Z")
        assert days is not None
        assert 0.05 < days < 0.07

    def test_returns_one_day_for_exact_24h(self) -> None:
        assert backfill.compute_cycle_days(
            "2026-04-08T00:00:00.000Z", "2026-04-09T00:00:00.000Z"
        ) == pytest.approx(1.0)

    def test_returns_none_when_started_at_missing(self) -> None:
        assert backfill.compute_cycle_days(None, "2026-04-08T01:28:14.880Z") is None

    def test_returns_none_when_completed_at_missing(self) -> None:
        assert backfill.compute_cycle_days("2026-04-08T00:05:46.207Z", None) is None

    def test_returns_none_when_completed_before_started(self) -> None:
        # Guard against bad data; negative cycle times are never meaningful.
        assert (
            backfill.compute_cycle_days("2026-04-09T00:00:00.000Z", "2026-04-08T00:00:00.000Z")
            is None
        )


# ---------------------------------------------------------------------------
# format_delta
# ---------------------------------------------------------------------------


class TestFormatDelta:
    @pytest.mark.parametrize(
        ("planned", "actual", "expected"),
        [
            (5, 5, "+0"),
            (3, 5, "+2"),
            (5, 3, "-2"),
            (1, 0, "-1"),
        ],
    )
    def test_known_signs(self, planned: int, actual: int, expected: str) -> None:
        assert backfill.format_delta(planned, actual) == expected

    def test_missing_actual_returns_na(self) -> None:
        assert backfill.format_delta(5, None) == "n/a"

    def test_missing_planned_returns_na(self) -> None:
        assert backfill.format_delta(None, 5) == "n/a"


# ---------------------------------------------------------------------------
# render_actual_cell
# ---------------------------------------------------------------------------


class TestRenderActualCell:
    def test_intra_day_cycle_rounds_to_under_one_day(self) -> None:
        issue = _make_issue(
            started_at="2026-04-08T00:05:46.207Z",
            completed_at="2026-04-08T01:28:14.880Z",
            estimate_value=3,
        )
        assert backfill.render_actual_cell(issue) == "3 pts (<1 day)"

    def test_multi_day_cycle_rounds_to_calendar_days(self) -> None:
        issue = _make_issue(
            started_at="2026-04-08T00:00:00.000Z",
            completed_at="2026-04-11T00:00:00.000Z",
            estimate_value=5,
        )
        assert backfill.render_actual_cell(issue) == "5 pts (3 days)"

    def test_one_day_cycle_uses_singular(self) -> None:
        issue = _make_issue(
            started_at="2026-04-08T00:00:00.000Z",
            completed_at="2026-04-09T00:00:00.000Z",
            estimate_value=5,
        )
        assert backfill.render_actual_cell(issue) == "5 pts (1 day)"

    def test_missing_issue_returns_n_a(self) -> None:
        assert backfill.render_actual_cell(None) == "n/a"

    def test_missing_estimate_renders_unknown_points(self) -> None:
        issue = _make_issue(estimate_value=None)
        assert backfill.render_actual_cell(issue).startswith("? pts")

    def test_missing_timestamps_renders_unknown_cycle(self) -> None:
        issue = _make_issue(started_at=None, completed_at=None)
        assert backfill.render_actual_cell(issue) == "3 pts (? days)"


# ---------------------------------------------------------------------------
# build_csv_row
# ---------------------------------------------------------------------------


class TestBuildCsvRow:
    def test_regular_story_with_complete_data(self) -> None:
        issue = _make_issue(
            started_at="2026-04-08T00:00:00.000Z",
            completed_at="2026-04-09T00:00:00.000Z",
            estimate_value=5,
        )
        row = backfill.build_csv_row("S-139A", "SEE-174", issue, planned_pts=3)
        assert row == {
            "story_id": "S-139A",
            "linear_id": "SEE-174",
            "planned_pts": 3,
            "actual_pts": 5,
            "started_at": "2026-04-08T00:00:00.000Z",
            "completed_at": "2026-04-09T00:00:00.000Z",
            "cycle_days": 1.0,
            "delta": "+2",
            "status": "ok",
        }

    def test_missing_issue_marks_row_missing(self) -> None:
        row = backfill.build_csv_row("S-175", None, None, planned_pts=5)
        assert row["status"] == "missing"
        assert row["linear_id"] == ""
        assert row["actual_pts"] is None
        assert row["cycle_days"] is None
        assert row["delta"] == "n/a"

    def test_partial_data_keeps_status_ok(self) -> None:
        # Missing estimate but valid timestamps → still "ok" so the row is
        # rendered; the actual cell shows "? pts".
        issue = _make_issue(estimate_value=None)
        row = backfill.build_csv_row("S-XYZ", "SEE-999", issue, planned_pts=2)
        assert row["status"] == "ok"
        assert row["actual_pts"] is None
        assert row["delta"] == "n/a"


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------


class TestWriteCsv:
    def test_round_trip_preserves_columns_and_order(self, tmp_path: Path) -> None:
        rows = [
            {
                "story_id": "S-139A",
                "linear_id": "SEE-174",
                "planned_pts": 3,
                "actual_pts": 3,
                "started_at": "2026-04-08T00:00:00.000Z",
                "completed_at": "2026-04-08T01:00:00.000Z",
                "cycle_days": 0.042,
                "delta": "+0",
                "status": "ok",
            },
            {
                "story_id": "S-175",
                "linear_id": "",
                "planned_pts": 5,
                "actual_pts": None,
                "started_at": None,
                "completed_at": None,
                "cycle_days": None,
                "delta": "n/a",
                "status": "missing",
            },
        ]
        dest = tmp_path / "actuals.csv"
        backfill.write_csv(rows, dest)

        with dest.open(newline="", encoding="utf-8") as fp:
            reader = csv.DictReader(fp)
            assert reader.fieldnames == [
                "story_id",
                "linear_id",
                "planned_pts",
                "actual_pts",
                "started_at",
                "completed_at",
                "cycle_days",
                "delta",
                "status",
            ]
            loaded = list(reader)

        assert loaded[0]["story_id"] == "S-139A"
        assert loaded[1]["status"] == "missing"
        # None-valued cells are serialised as empty strings.
        assert loaded[1]["actual_pts"] == ""
        assert loaded[1]["cycle_days"] == ""

    def test_cycle_days_rounded_to_four_decimals(self, tmp_path: Path) -> None:
        rows = [
            {
                "story_id": "S-1",
                "linear_id": "SEE-1",
                "planned_pts": 1,
                "actual_pts": 1,
                "started_at": "2026-01-01T00:00:00.000Z",
                "completed_at": "2026-01-01T00:00:01.000Z",
                # Raw float would serialise as 1.1574074074074074e-05 — noisy.
                "cycle_days": 0.0000115740740740740,
                "delta": "+0",
                "status": "ok",
            }
        ]
        dest = tmp_path / "actuals.csv"
        backfill.write_csv(rows, dest)
        text = dest.read_text(encoding="utf-8")
        # 0.0000... rounds to 0.0 at 4 decimals — csv writes the plain literal.
        assert ",0.0," in text
        assert "e-05" not in text  # no float-repr noise

    def test_creates_missing_parent_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "nested" / "actuals.csv"
        backfill.write_csv([], dest)
        assert dest.exists()

    def test_empty_input_writes_header_only(self, tmp_path: Path) -> None:
        dest = tmp_path / "actuals.csv"
        backfill.write_csv([], dest)
        text = dest.read_text(encoding="utf-8")
        assert text.startswith("story_id,linear_id,")
        # Exactly one line: the header.
        assert text.count("\n") == 1


# ---------------------------------------------------------------------------
# update_markdown_table
# ---------------------------------------------------------------------------


_RAW_TABLE = (
    "| Story | Linear | Title | Planned pts | Status | Actual pts |\n"
    "|---|---|---|---:|---|---:|\n"
    "| S-139A | SEE-174 | Docs infrastructure (MkDocs + CI/CD) | 3 | Done |"
    " TBD (live data extract deferred to S-180-F3) |\n"
    "| S-139B | SEE-175 | Security concepts primer | 5 | Done | TBD |\n"
    "| S-175 | — | Ops Primer — operational intelligence concepts | 5 | Done | TBD |\n"
    "| S-176 | — | Dual-lens integration — SRE persona path + ops examples"
    " | 3 | Done | TBD |\n"
)


class TestUpdateMarkdownTable:
    def test_replaces_tbd_cell_for_matching_row(self) -> None:
        rows = [
            {
                "story_id": "S-139A",
                "linear_id": "SEE-174",
                "actual_cell": "3 pts (<1 day)",
                "status": "ok",
            }
        ]
        result = backfill.update_markdown_table(_RAW_TABLE, rows)
        # The matched row has its TBD cell replaced.
        assert (
            "| S-139A | SEE-174 | Docs infrastructure (MkDocs + CI/CD) | 3 |"
            " Done | 3 pts (<1 day) |"
        ) in result
        # Other rows untouched.
        assert "| S-139B | SEE-175 | Security concepts primer | 5 | Done | TBD |" in result

    def test_replaces_em_dash_linear_id_rows(self) -> None:
        # S-175 has no Linear ID in the markdown (em-dash placeholder) but we
        # know SEE-186 in the data set — the helper must still match by story
        # id when linear_id is em-dash.
        rows = [
            {
                "story_id": "S-175",
                "linear_id": "SEE-186",
                "actual_cell": "5 pts (<1 day)",
                "status": "ok",
            }
        ]
        result = backfill.update_markdown_table(_RAW_TABLE, rows)
        assert (
            "| S-175 | SEE-186 | Ops Primer — operational intelligence concepts |"
            " 5 | Done | 5 pts (<1 day) |"
        ) in result

    def test_idempotent_when_run_twice(self) -> None:
        rows = [
            {
                "story_id": "S-139A",
                "linear_id": "SEE-174",
                "actual_cell": "3 pts (<1 day)",
                "status": "ok",
            }
        ]
        once = backfill.update_markdown_table(_RAW_TABLE, rows)
        twice = backfill.update_markdown_table(once, rows)
        assert once == twice

    def test_unknown_story_id_is_no_op(self) -> None:
        rows = [
            {
                "story_id": "S-999X",
                "linear_id": "SEE-9999",
                "actual_cell": "0 pts (n/a)",
                "status": "missing",
            }
        ]
        assert backfill.update_markdown_table(_RAW_TABLE, rows) == _RAW_TABLE

    def test_missing_status_falls_back_to_explanatory_marker(self) -> None:
        rows = [
            {
                "story_id": "S-175",
                "linear_id": None,
                "actual_cell": "n/a",
                "status": "missing",
            }
        ]
        result = backfill.update_markdown_table(_RAW_TABLE, rows)
        # The em-dash row stays em-dash for the linear column and shows the
        # explanatory marker.
        assert (
            "| S-175 | — | Ops Primer — operational intelligence concepts |"
            " 5 | Done | n/a [^missing-linear] |"
        ) in result
