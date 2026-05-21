"""Tests for the docs-drift checker.

The helpers under test live in ``documents/seerflow-guide-staging/scripts/check_docs_drift.py``.
We exercise each helper in isolation with synthetic fixtures so the suite does
not depend on the real ``seerflow`` package being importable.
"""

from __future__ import annotations

import argparse

# The script is imported via its on-disk path so the test runs regardless of
# how the staging tree is mounted relative to ``sys.path``. ``importlib`` keeps
# the import side-effect-free.
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "drift_check" / "check_docs_drift.py"
_spec = importlib.util.spec_from_file_location("check_docs_drift", _SCRIPT_PATH)
assert _spec and _spec.loader, "could not load check_docs_drift module spec"
check_docs_drift = importlib.util.module_from_spec(_spec)
sys.modules["check_docs_drift"] = check_docs_drift
_spec.loader.exec_module(check_docs_drift)


# ---------------------------------------------------------------------------
# Config-drift helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeLeaf:
    """Leaf dataclass — fields are all scalars."""

    alpha: float = 0.1
    beta: int = 7


@dataclass(frozen=True)
class _FakeRoot:
    """Root dataclass — has one nested dataclass and one scalar field."""

    leaf: _FakeLeaf
    name: str = "root"


def test_collect_schema_keys_from_dataclass_returns_dotted_keys() -> None:
    """Nested dataclass fields are flattened into ``parent.child`` form."""

    keys = check_docs_drift.collect_schema_keys(_FakeRoot)
    assert keys == frozenset({"leaf.alpha", "leaf.beta", "name"})


def test_parse_config_yaml_blocks_returns_documented_keys() -> None:
    """Fenced YAML blocks are parsed and flattened to dotted keys."""

    markdown = """
Some prose.

```yaml
leaf:
  alpha: 0.2
  beta: 9
name: hello
```

More prose with non-yaml fenced block:

```python
print("not parsed")
```
"""
    keys = check_docs_drift.parse_config_yaml_blocks(markdown)
    assert keys == frozenset({"leaf.alpha", "leaf.beta", "name"})


def test_diff_config_keys_returns_drift_report() -> None:
    """Schema keys minus doc keys = missing; doc keys minus schema = extra."""

    schema_keys = frozenset({"a.b", "c"})
    docs_keys = frozenset({"a.b", "d"})
    report = check_docs_drift.diff_config_keys(schema_keys, docs_keys)
    assert report.extra_in_docs == frozenset({"d"})
    assert report.missing_in_docs == frozenset({"c"})
    assert report.ok is False


def test_diff_config_keys_ok_when_doc_subset_of_schema() -> None:
    """If docs document a strict subset of the schema, the report is OK.

    Missing-in-docs is a warning, not an error — only extra-in-docs (drifted)
    breaks the build.
    """

    schema_keys = frozenset({"a.b", "c", "d"})
    docs_keys = frozenset({"a.b", "c"})
    report = check_docs_drift.diff_config_keys(schema_keys, docs_keys)
    assert report.extra_in_docs == frozenset()
    assert report.missing_in_docs == frozenset({"d"})
    assert report.ok is True


# ---------------------------------------------------------------------------
# CLI-drift helpers
# ---------------------------------------------------------------------------


def _build_synthetic_parser() -> argparse.ArgumentParser:
    """Build a small argparse parser with subparsers for the CLI tests."""

    parser = argparse.ArgumentParser(prog="fake")
    parser.add_argument("--config", help="ignored top-level flag")
    parser.add_argument("--global-flag", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    a = sub.add_parser("alpha")
    a.add_argument("--alpha-only")

    b = sub.add_parser("beta")
    b.add_argument("--beta-only")
    b.add_argument("--shared")

    return parser


def test_collect_cli_flags_walks_subparsers() -> None:
    """Every long-form flag — top-level + subparser — appears in the set."""

    parser = _build_synthetic_parser()
    flags = check_docs_drift.collect_cli_flags(parser)
    assert "--global-flag" in flags
    assert "--alpha-only" in flags
    assert "--beta-only" in flags
    assert "--shared" in flags


def test_collect_cli_flags_ignores_help_and_version_and_config() -> None:
    """``--help``, ``--version``, ``--config`` are universally excluded."""

    parser = _build_synthetic_parser()
    flags = check_docs_drift.collect_cli_flags(parser)
    assert "--help" not in flags
    assert "--version" not in flags
    assert "--config" not in flags


def test_parse_doc_cli_flags_extracts_long_flags() -> None:
    """Markdown text is scanned for ``--flag`` mentions; ignored ones drop."""

    markdown = """
Run with `--foo` and `--bar=value`.

```bash
fake alpha --baz --foo
fake --help
```
"""
    flags = check_docs_drift.parse_doc_cli_flags(markdown)
    assert flags == frozenset({"--foo", "--bar", "--baz"})


def test_diff_cli_flags_returns_drift_report() -> None:
    """Drift logic mirrors config: doc-extra breaks the build, missing warns."""

    cli_flags = frozenset({"--foo", "--bar"})
    doc_flags = frozenset({"--foo", "--qux"})
    report = check_docs_drift.diff_cli_flags(cli_flags, doc_flags)
    assert report.extra_in_docs == frozenset({"--qux"})
    assert report.missing_in_docs == frozenset({"--bar"})
    assert report.ok is False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _write_docs_fixture(
    docs_dir: Path,
    *,
    config_keys: list[str],
    cli_flags: list[str],
) -> None:
    """Write minimal ``configuration.md`` + ``cli.md`` reflecting the inputs."""

    ref = docs_dir / "reference"
    ref.mkdir(parents=True, exist_ok=True)

    yaml_lines = []
    nested: dict[str, list[str]] = {}
    for key in config_keys:
        if "." in key:
            parent, child = key.split(".", 1)
            nested.setdefault(parent, []).append(child)
        else:
            yaml_lines.append(f"{key}: 0")
    for parent, children in nested.items():
        yaml_lines.append(f"{parent}:")
        for child in children:
            yaml_lines.append(f"  {child}: 0")
    yaml_block = "\n".join(yaml_lines)
    (ref / "configuration.md").write_text(
        f"# Config\n\n```yaml\n{yaml_block}\n```\n",
        encoding="utf-8",
    )

    cli_lines = "\n".join(f"`{flag}`" for flag in cli_flags)
    (ref / "cli.md").write_text(
        f"# CLI\n\n{cli_lines}\n",
        encoding="utf-8",
    )


def test_main_exits_nonzero_on_drift_and_writes_json(tmp_path: Path) -> None:
    """When docs mention a config key that doesn't exist in the schema,

    ``main()`` writes the JSON report and exits non-zero.
    """

    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs_fixture(
        docs,
        config_keys=["name", "leaf.alpha", "leaf.ghost"],  # leaf.ghost is drift
        cli_flags=["--global-flag", "--alpha-only", "--phantom"],  # --phantom drift
    )
    report_path = tmp_path / "drift-report.json"

    parser = _build_synthetic_parser()

    with pytest.raises(SystemExit) as exc:
        check_docs_drift.main(
            [
                "--docs-dir",
                str(docs),
                "--report-path",
                str(report_path),
            ],
            schema_root_cls=_FakeRoot,
            parser_factory=lambda: parser,
        )
    assert exc.value.code == 1
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "leaf.ghost" in payload["config"]["extra_in_docs"]
    assert "--phantom" in payload["cli"]["extra_in_docs"]


def test_main_exits_zero_when_docs_match_schema(tmp_path: Path) -> None:
    """Clean docs → no SystemExit, JSON report shows empty extra sets."""

    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs_fixture(
        docs,
        config_keys=["name", "leaf.alpha", "leaf.beta"],
        cli_flags=["--global-flag", "--alpha-only", "--beta-only", "--shared"],
    )
    report_path = tmp_path / "drift-report.json"
    parser = _build_synthetic_parser()

    # main() returns None on success — no SystemExit raised
    check_docs_drift.main(
        [
            "--docs-dir",
            str(docs),
            "--report-path",
            str(report_path),
        ],
        schema_root_cls=_FakeRoot,
        parser_factory=lambda: parser,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["config"]["extra_in_docs"] == []
    assert payload["cli"]["extra_in_docs"] == []


def test_main_only_config_check(tmp_path: Path) -> None:
    """``--check config`` skips CLI drift and exits non-zero only on config issues."""

    docs = tmp_path / "docs"
    docs.mkdir()
    _write_docs_fixture(
        docs,
        config_keys=["name", "leaf.alpha"],
        cli_flags=["--phantom"],  # would normally drift, but we skip CLI
    )
    report_path = tmp_path / "drift-report.json"
    parser = _build_synthetic_parser()

    check_docs_drift.main(
        [
            "--docs-dir",
            str(docs),
            "--report-path",
            str(report_path),
            "--check",
            "config",
        ],
        schema_root_cls=_FakeRoot,
        parser_factory=lambda: parser,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "cli" not in payload
    assert payload["config"]["extra_in_docs"] == []
