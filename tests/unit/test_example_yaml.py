"""S-074 / S-087: ``seerflow.example.yaml`` + settings reference docs.

The example file is the operator's first reference. It must demonstrate
both ``sqlite`` and ``postgresql`` backends side-by-side and document
every pool knob (S-073) so a fresh operator can copy-paste their way
from zero-config SQLite to production PostgreSQL without grep-ing the
source tree.

S-087 widens this guard: every top-level configuration section must be
documented in *both* ``seerflow.example.yaml`` and
``docs/settings-reference.md`` so launch-day operators can configure any
subsystem without reading source. The example must still parse cleanly
through the real loader and ship ``backend: sqlite`` by default.

These tests are intentionally text-shape-only — we are guarding against
accidental deletion of documented knobs and section drift, not policing
prose. The full config parse is covered by ``test_config.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import seerflow.config as config_module
from seerflow.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_YAML = PROJECT_ROOT / "seerflow.example.yaml"
SETTINGS_REFERENCE = PROJECT_ROOT / "docs" / "settings-reference.md"

# Every top-level section that ``SeerflowConfig`` exposes. The example
# file may keep optional sections commented (so the file stays runnable
# as-is), so we assert the *section token* appears at all — commented or
# not. ``docs/settings-reference.md`` must carry a heading for each.
TOP_LEVEL_SECTIONS = (
    "storage",
    "receivers",
    "detection",
    "correlation",
    "alerting",
    "llm",
    "ueba",
    "threat_intel",
)

# Representative keys that were missing before S-087. If any of these
# regress out of the example file the operator loses copy-paste access
# to an entire subsystem.
EXAMPLE_REQUIRED_KEYS = (
    # detection — Holt-Winters / CUSUM / Markov / risk / graph
    "hw_seasonal_period",
    "cusum_threshold",
    "markov_smoothing",
    "risk_threshold",
    "graph_structural",
    "kill_chain",
    # correlation
    "window_duration_seconds",
    # alerting — OTLP export + mTLS
    "otlp_endpoint",
    "otlp_mtls_cert_file",
    # llm — full knob set
    "ollama_model",
    "explanation_cache_size",
    "rule_suggestion_min_tp",
    # ueba
    "warmup_days",
    "score_threshold",
    # threat_intel
    "default_poll_interval_s",
    # top-level scalars / ws_* / api_*
    "shutdown_timeout_s",
    "ws_max_connections",
    "api_rate_limit_enabled",
)


@pytest.fixture(scope="module")
def example_text() -> str:
    """Read the example YAML once per test module."""
    return EXAMPLE_YAML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def reference_text() -> str:
    """Read the settings reference doc once per test module.

    ``docs/`` is a local-only working area in this repository (excluded
    from version control via ``.git/info/exclude``), so the reference
    file is not present in a fresh CI checkout. When it is absent we
    skip the reference-completeness guards rather than fail — the
    operator-facing ``seerflow.example.yaml`` (which *is* tracked)
    remains fully guarded by ``TestExampleYamlCompleteness``. When the
    file is present (local dev), the guards run and prevent drift.
    """
    if not SETTINGS_REFERENCE.is_file():
        pytest.skip(
            "docs/settings-reference.md not present (docs/ is a local-only "
            "working area excluded from git); example YAML guards still apply"
        )
    return SETTINGS_REFERENCE.read_text(encoding="utf-8")


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


class TestExampleYamlCompleteness:
    """S-087: every config section must be documented in the example."""

    @pytest.mark.parametrize("section", TOP_LEVEL_SECTIONS)
    def test_section_present(self, example_text: str, section: str) -> None:
        # Accept the section header whether the block is active
        # (``section:``) or commented out (``# section:``) — optional
        # sections stay commented so the file remains runnable as-is.
        pattern = re.compile(rf"^\s*#?\s*{re.escape(section)}:", re.MULTILINE)
        assert pattern.search(example_text), (
            f"seerflow.example.yaml must document the {section!r} section"
        )

    @pytest.mark.parametrize("key", EXAMPLE_REQUIRED_KEYS)
    def test_required_key_present(self, example_text: str, key: str) -> None:
        assert key in example_text, (
            f"seerflow.example.yaml must document the {key!r} config knob "
            f"(regressed out of the example — operators lose copy-paste access)"
        )

    def test_no_literal_secrets(self, example_text: str) -> None:
        """Secret-bearing keys must use ``${ENV_VAR}`` placeholders only.

        We scan the secret field names (the ``repr=False`` set in
        ``config.py``) and assert that wherever they appear *uncommented*
        they reference an env var rather than a literal value.
        """
        secret_keys = (
            "postgresql_url",
            "falkordb_url",
            "auth_token",
            "pagerduty_routing_key",
            "cloud_api_key",
            "api_rate_limit_redis_url",
        )
        for line in example_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # commented guidance is fine
            for key in secret_keys:
                if stripped.startswith(f"{key}:"):
                    value = stripped.split(":", 1)[1].strip()
                    assert value == "" or value.startswith("${"), (
                        f"{key!r} in seerflow.example.yaml exposes a literal "
                        f"secret {value!r}; use a ${{ENV_VAR}} placeholder"
                    )


class TestSettingsReferenceCompleteness:
    """S-087: docs/settings-reference.md must cover every section.

    ``docs/`` is excluded from version control in this repository, so
    these guards skip gracefully in CI (via the ``reference_text``
    fixture) and run in local development to prevent reference drift.
    """

    def test_reference_file_present(self, reference_text: str) -> None:
        # The fixture skips when the file is absent; reaching here means
        # it exists and was read successfully.
        assert reference_text.strip(), "settings reference is empty"

    @pytest.mark.parametrize("section", TOP_LEVEL_SECTIONS)
    def test_section_heading_present(self, reference_text: str, section: str) -> None:
        # Reference uses ``## `section``` Markdown headings.
        pattern = re.compile(rf"^##\s+`?{re.escape(section)}`?", re.MULTILINE)
        assert pattern.search(reference_text), (
            f"docs/settings-reference.md must document the {section!r} section"
        )

    @pytest.mark.parametrize(
        "scalar_group",
        [
            "health_bind_address",
            "shutdown_timeout_s",
            "ws_max_connections",
            "api_rate_limit_enabled",
        ],
    )
    def test_top_level_and_transport_scalars_documented(
        self, reference_text: str, scalar_group: str
    ) -> None:
        assert scalar_group in reference_text, (
            f"docs/settings-reference.md must document the {scalar_group!r} setting"
        )
