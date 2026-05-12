"""S-074: ``seerflow.example.yaml`` documents both storage backends.

The example file is the operator's first reference. It must demonstrate
both ``sqlite`` and ``postgresql`` backends side-by-side and document
every pool knob (S-073) so a fresh operator can copy-paste their way
from zero-config SQLite to production PostgreSQL without grep-ing the
source tree.

These tests are intentionally text-shape-only — we are guarding against
accidental deletion of documented knobs, not policing prose. The full
config parse is covered by ``test_config.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import seerflow.config as config_module
from seerflow.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_YAML = PROJECT_ROOT / "seerflow.example.yaml"


@pytest.fixture(scope="module")
def example_text() -> str:
    """Read the example YAML once per test module."""
    return EXAMPLE_YAML.read_text(encoding="utf-8")


class TestExampleYamlExists:
    def test_file_present(self) -> None:
        assert EXAMPLE_YAML.is_file(), f"missing example yaml: {EXAMPLE_YAML}"


class TestStorageBlock:
    """The storage block documents both backends + every pool knob."""

    def test_default_backend_is_sqlite(self, example_text: str) -> None:
        # First line referring to the storage backend should keep the
        # zero-config default visible — operators should not need to read
        # the comment to discover the default.
        assert "backend: sqlite" in example_text

    def test_documents_both_backends(self, example_text: str) -> None:
        assert "sqlite | postgresql" in example_text

    @pytest.mark.parametrize(
        "knob",
        [
            "sqlite_path",
            "postgresql_url",
            "postgresql_pool_min_size",
            "postgresql_pool_max_size",
            "postgresql_command_timeout_s",
            "data_dir",
        ],
    )
    def test_pool_knob_documented(self, example_text: str, knob: str) -> None:
        assert knob in example_text, (
            f"seerflow.example.yaml must document the {knob!r} storage knob"
        )

    def test_postgres_extra_install_hint(self, example_text: str) -> None:
        """Operator hint for the ``postgres`` extra appears in the example."""
        # Either the literal command or the extra name is enough — we are
        # asserting the operator has a copy-paste path, not policing wording.
        assert "uv sync --extra postgres" in example_text or "extra postgres" in example_text


class TestExampleYamlParses:
    """The example file must parse cleanly via the real loader."""

    def test_load_succeeds(self) -> None:
        cfg = load_config(str(EXAMPLE_YAML))
        # The example file ships with backend=sqlite by default — this is
        # the same invariant as ``test_default_backend_is_sqlite`` above but
        # checked through the full loader so a future YAML-syntax mistake
        # does not silently sneak past the text-shape tests.
        assert cfg.storage.backend == "sqlite"
        # Module reference is intentional: documents that the example file
        # is the canonical entry point into the real ``seerflow.config``
        # surface, not a sandbox copy.
        assert hasattr(config_module, "load_config")
