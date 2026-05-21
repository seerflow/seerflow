"""S-086: ``CONTRIBUTING.md`` structure guard.

We do not police prose. We guard that the contributing guide exists and
documents the *actual* repo workflow (uv, pre-commit, conventional commits,
PR base ``dev``, 95% coverage gate) so a contributor following it cannot get
the process wrong.

If the workflow changes, update both this guard and the guide in the same
commit — do not silently drop sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRIBUTING = PROJECT_ROOT / "CONTRIBUTING.md"


@pytest.fixture(scope="module")
def guide_text() -> str:
    return CONTRIBUTING.read_text(encoding="utf-8")


def test_file_present() -> None:
    assert CONTRIBUTING.is_file(), f"missing contributing guide: {CONTRIBUTING}"


@pytest.mark.parametrize(
    "heading",
    [
        "Development Setup",
        "Quality Gates",
        "Branching",
        "Pull Requests",
    ],
)
def test_required_heading_present(guide_text: str, heading: str) -> None:
    assert heading in guide_text, f"CONTRIBUTING.md missing required section: {heading!r}"


@pytest.mark.parametrize(
    "needle",
    [
        "uv sync",
        "pre-commit",
        "Conventional Commits",
        "--cov-fail-under=95",
    ],
)
def test_documents_real_workflow(guide_text: str, needle: str) -> None:
    assert needle in guide_text, (
        f"CONTRIBUTING.md must document {needle!r} (it is part of the enforced repo workflow)"
    )


def test_pr_base_branch_is_dev(guide_text: str) -> None:
    """PRs target `dev`, never `main` directly — this must be explicit."""
    assert "`dev`" in guide_text, (
        "CONTRIBUTING.md must state that pull requests target the `dev` branch"
    )
    lower = guide_text.lower()
    assert "main" in lower and "dev" in lower, (
        "CONTRIBUTING.md must explain the dev -> main branching model"
    )
