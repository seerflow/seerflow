"""Structural tests for the ``.github/workflows/docs-drift.yml`` workflow.

These tests guard against silent breakage of the docs-drift CI gate:

* The workflow must trigger only on PRs that touch ``src/seerflow/config.py``
  or ``src/seerflow/cli.py``.
* The job must clone ``seerflow/seerflow-guide`` and run the seerflow-side
  wrapper script (``scripts/check_docs_drift.py``).

A YAML parse is enough — we are validating the contract, not executing it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "docs-drift.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    """Parse the docs-drift workflow YAML once per test module."""

    assert WORKFLOW_PATH.is_file(), f"workflow file missing: {WORKFLOW_PATH}"
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "workflow YAML must parse to a mapping"
    return loaded


def test_docs_drift_workflow_yaml_parses(workflow: dict[str, Any]) -> None:
    """The workflow has a name, a pull_request trigger with the right paths."""

    assert workflow.get("name"), "workflow must declare a name"

    # PyYAML loads the ``on:`` key as the Python boolean ``True``. Accept either
    # form so a future YAML loader change does not break the test silently.
    triggers = workflow.get("on") or workflow.get(True)
    assert isinstance(triggers, dict), "workflow must declare a mapping of triggers"

    pull_request = triggers.get("pull_request")
    assert isinstance(pull_request, dict), "pull_request trigger must be configured"

    paths = pull_request.get("paths")
    assert isinstance(paths, list), "pull_request.paths must be a list"
    assert "src/seerflow/config.py" in paths
    assert "src/seerflow/cli.py" in paths

    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow must declare at least one job"
    for job in jobs.values():
        assert isinstance(job, dict)
        steps = job.get("steps")
        assert isinstance(steps, list) and steps, "every job must declare steps"


def test_docs_drift_workflow_invokes_wrapper_script(workflow: dict[str, Any]) -> None:
    """The workflow clones seerflow-guide and runs our wrapper script."""

    rendered = yaml.safe_dump(workflow)
    assert "seerflow/seerflow-guide" in rendered, "workflow must check out seerflow/seerflow-guide"
    assert ".github/check_docs_drift.py" in rendered, (
        "workflow must invoke .github/check_docs_drift.py"
    )


def test_docs_drift_workflow_uses_python_311(workflow: dict[str, Any]) -> None:
    """The workflow pins Python 3.11 to match the rest of seerflow's CI matrix."""

    rendered = yaml.safe_dump(workflow)
    assert "3.11" in rendered, "workflow should pin Python 3.11"
