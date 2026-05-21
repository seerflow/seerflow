"""S-085: structural guard for the release publish workflow.

The acceptance criterion is "tag -> build -> test -> publish". release-please
owns the tag; this test asserts the ``publish`` job in ``release.yml`` runs
the quality-gate test suite *and* ``twine check`` *before* the
``pypa/gh-action-pypi-publish`` step, so a broken build or a malformed
long-description can never reach PyPI.

Parses the workflow as YAML — no GitHub runner needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
PUBLISH_YML = REPO_ROOT / ".github" / "workflows" / "publish.yml"


@pytest.fixture(scope="module")
def publish_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))
    publish = workflow["jobs"]["publish"]
    steps = publish["steps"]
    assert isinstance(steps, list) and steps, "publish job has no steps"
    return steps


def _index_of(steps: list[dict[str, Any]], predicate: Any) -> int:
    for i, step in enumerate(steps):
        if predicate(step):
            return i
    return -1


def test_release_yml_is_valid_yaml() -> None:
    workflow = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))
    assert "jobs" in workflow
    assert "publish" in workflow["jobs"]


def test_single_canonical_publish_workflow() -> None:
    """S-086 (deferred S-085 #2): exactly one PyPI-publish entrypoint.

    ``release.yml`` is the canonical, gated path (release-please tag ->
    frontend build -> ``uv build`` -> quality gates -> ``twine check`` ->
    upload). The old ``publish.yml`` (``release: published`` trigger) was an
    ungated duplicate that fired on the *same* GitHub Release release-please
    creates, risking a double upload. It must not come back.
    """
    assert RELEASE_YML.is_file(), (
        "release.yml is the canonical PyPI publish workflow and must exist"
    )
    assert not PUBLISH_YML.is_file(), (
        "publish.yml is a redundant, ungated PyPI publish workflow that "
        "double-fires with release.yml on the same GitHub Release — it must "
        "stay deleted; release.yml is the single canonical publish path"
    )


def test_publish_runs_tests_before_pypi_upload(
    publish_steps: list[dict[str, Any]],
) -> None:
    pytest_idx = _index_of(
        publish_steps,
        lambda s: "pytest" in str(s.get("run", "")),
    )
    publish_idx = _index_of(
        publish_steps,
        lambda s: "pypa/gh-action-pypi-publish" in str(s.get("uses", "")),
    )
    assert pytest_idx != -1, "publish job runs no `pytest` step"
    assert publish_idx != -1, "publish job has no PyPI upload step"
    assert pytest_idx < publish_idx, (
        "tests must run before the PyPI upload (tag -> build -> test -> publish)"
    )


def test_publish_runs_twine_check_before_upload(
    publish_steps: list[dict[str, Any]],
) -> None:
    twine_idx = _index_of(
        publish_steps,
        lambda s: "twine check" in str(s.get("run", "")),
    )
    publish_idx = _index_of(
        publish_steps,
        lambda s: "pypa/gh-action-pypi-publish" in str(s.get("uses", "")),
    )
    assert twine_idx != -1, "publish job has no `twine check` step"
    assert publish_idx != -1, "publish job has no PyPI upload step"
    assert twine_idx < publish_idx, "`twine check` must run before PyPI upload"


def test_build_runs_before_tests(publish_steps: list[dict[str, Any]]) -> None:
    build_idx = _index_of(
        publish_steps,
        lambda s: "uv build" in str(s.get("run", "")),
    )
    pytest_idx = _index_of(
        publish_steps,
        lambda s: "pytest" in str(s.get("run", "")),
    )
    assert build_idx != -1, "publish job has no `uv build` step"
    assert pytest_idx != -1, "publish job runs no `pytest` step"
    assert build_idx < pytest_idx, "build must precede the test gate"
