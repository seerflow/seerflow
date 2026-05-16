"""S-086: ``README.md`` structure guard.

We do not police prose. We guard against accidental deletion / refactor that
drops the acceptance-criteria elements: a Mermaid architecture diagram, an
Installation section, the documented sub-5-minute quickstart, the PyPI
install path, and a Seerflow-vs-Wazuh-vs-Splunk comparison table.

If a future change reorganises these, update both this guard and the README
in the same commit — do not silently drop sections.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
README = PROJECT_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_file_present() -> None:
    assert README.is_file(), f"missing README: {README}"


def test_has_mermaid_diagram(readme_text: str) -> None:
    """Architecture diagram must be a GitHub-renderable Mermaid fenced block."""
    assert re.search(r"^```mermaid\s*$", readme_text, re.MULTILINE), (
        "README must contain a ```mermaid fenced code block (AC: architecture diagram as Mermaid)"
    )


def test_has_installation_section(readme_text: str) -> None:
    assert re.search(r"^#{1,3}\s+Install", readme_text, re.MULTILINE), (
        "README must contain an Installation section"
    )


def test_documents_pypi_install_path(readme_text: str) -> None:
    assert "pip install seerflow" in readme_text, (
        "README must document the PyPI install path `pip install seerflow` "
        "(shipped by S-085) — it is the fastest zero-to-alert path"
    )


def test_quickstart_states_five_minute_target(readme_text: str) -> None:
    assert "5 minutes" in readme_text, (
        "README quickstart must document the zero-to-first-alert in <5 minutes target (AC)"
    )


def test_has_comparison_table(readme_text: str) -> None:
    """A Markdown comparison table naming Wazuh and Splunk must exist."""
    assert "Wazuh" in readme_text, "comparison table must mention Wazuh"
    assert "Splunk" in readme_text, "comparison table must mention Splunk"
    # A GitHub Markdown table separator row, e.g. | --- | --- | --- |
    assert re.search(r"\|\s*:?-{3,}:?\s*\|", readme_text), (
        "README must contain a Markdown comparison table (Seerflow vs Wazuh vs Splunk)"
    )


def test_links_contributing_guide(readme_text: str) -> None:
    assert "CONTRIBUTING.md" in readme_text, "README must link to the contributing guide"
