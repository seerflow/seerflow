"""S-074: ``STORAGE_MIGRATION.md`` ops runbook structure guard.

The runbook is the only operator-facing migration document Seerflow ships.
We do not police prose — we guard against accidental wholesale deletion
or refactoring that drops the headings operators look for.

If a future change reorganises the headings, update the expected set here
and in the runbook in the same commit; do not silently delete sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = PROJECT_ROOT / "STORAGE_MIGRATION.md"


@pytest.fixture(scope="module")
def runbook_text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


class TestStorageMigrationRunbook:
    def test_file_present(self) -> None:
        assert RUNBOOK.is_file(), f"missing runbook: {RUNBOOK}"

    @pytest.mark.parametrize(
        "heading",
        [
            "Prerequisites",
            "Migration Procedure",
            "Validation",
            "Rollback",
        ],
    )
    def test_heading_present(self, runbook_text: str, heading: str) -> None:
        assert heading in runbook_text, (
            f"STORAGE_MIGRATION.md missing required section: {heading!r}"
        )

    def test_calls_out_no_in_place_copy(self, runbook_text: str) -> None:
        """Operator must learn upfront that data is not auto-migrated."""
        lower = runbook_text.lower()
        assert "do not" in lower or "does not" in lower or "no automatic" in lower, (
            "Runbook should explicitly state that SQLite rows are not "
            "automatically copied to PostgreSQL — operator action is required."
        )

    def test_mentions_postgres_extra_install(self, runbook_text: str) -> None:
        assert "uv sync --extra postgres" in runbook_text
