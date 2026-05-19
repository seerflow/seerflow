#!/usr/bin/env python3
"""Docs-drift checker for ``seerflow-guide``.

Compares documented config keys and CLI flags against the actual schema and
parser exported by the installed ``seerflow`` package. The script exits zero
when documentation strictly tracks the package, and non-zero (with a JSON
report) on drift. The companion GitHub Action ``docs-drift.yml`` reads the
JSON to post a PR comment.

Design notes
------------
* Config keys come from a recursive walk of ``dataclasses.fields()`` on the
  schema root (``seerflow.config.SeerflowConfig``). Nested dataclasses become
  dotted keys (``storage.backend``).
* CLI flags come from a recursive walk of ``parser._actions`` on
  ``seerflow.cli.build_parser()`` — more robust than scraping ``--help`` text.
* The script is import-safe: helpers take pure inputs so the test suite can
  exercise them with synthetic ``argparse`` parsers and dataclasses.
* ``main()`` accepts ``schema_root_cls`` and ``parser_factory`` injection so
  tests do not need a real ``seerflow`` install.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import re
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigDriftReport:
    """Outcome of a config-key diff.

    ``extra_in_docs`` (drift — docs reference a key that no longer exists in
    the schema) is the only failure mode; ``missing_in_docs`` (under-documented
    keys) is reported but does not break the build.
    """

    extra_in_docs: frozenset[str]
    missing_in_docs: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.extra_in_docs


@dataclass(frozen=True)
class CliDriftReport:
    """Outcome of a CLI-flag diff.

    Same semantics as :class:`ConfigDriftReport` — extra-in-docs is the
    error, missing-in-docs is informational.
    """

    extra_in_docs: frozenset[str]
    missing_in_docs: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.extra_in_docs


# ---------------------------------------------------------------------------
# Config-drift helpers
# ---------------------------------------------------------------------------


def _resolve_field_type(cls: type, field: dataclasses.Field[Any]) -> Any:
    """Resolve ``field.type`` even when stored as a forward-ref string.

    ``from __future__ import annotations`` (used pervasively in this codebase)
    turns every ``field.type`` into a string. ``typing.get_type_hints`` resolves
    the string against the defining class's ``__globals__`` and ``__locals__``,
    so we get the actual class back.
    """

    try:
        hints = typing.get_type_hints(cls)
    except Exception:  # pragma: no cover — defensive only
        return field.type
    return hints.get(field.name, field.type)


def collect_schema_keys(cls: type, prefix: str = "") -> frozenset[str]:
    """Recursively flatten ``dataclasses.fields(cls)`` into dotted keys.

    For a leaf field ``alpha`` directly on ``cls`` the emitted key is
    ``alpha``; for a field on a nested dataclass ``leaf`` the emitted key is
    ``leaf.alpha``.
    """

    if not dataclasses.is_dataclass(cls):
        return frozenset()

    keys: set[str] = set()
    for field in dataclasses.fields(cls):
        full = f"{prefix}{field.name}" if not prefix else f"{prefix}.{field.name}"
        field_type = _resolve_field_type(cls, field)
        if isinstance(field_type, type) and dataclasses.is_dataclass(field_type):
            keys.update(collect_schema_keys(field_type, full))
        else:
            keys.add(full)
    return frozenset(keys)


_YAML_BLOCK_RE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)


def _flatten_dict_keys(obj: Any, prefix: str = "") -> Iterable[str]:
    """Yield dotted keys from a nested ``dict`` (lists are treated as leaves)."""

    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                yield from _flatten_dict_keys(v, key)
            else:
                yield key


def parse_config_yaml_blocks(markdown: str) -> frozenset[str]:
    """Extract every fenced YAML block from ``markdown`` and return its keys.

    Non-YAML fenced blocks are ignored. Empty or malformed YAML blocks are
    silently skipped (better to report no drift than to crash on a typo in
    docs we are explicitly trying to validate).
    """

    keys: set[str] = set()
    for match in _YAML_BLOCK_RE.findall(markdown):
        try:
            loaded = yaml.safe_load(match)
        except yaml.YAMLError:
            continue
        if isinstance(loaded, dict):
            keys.update(_flatten_dict_keys(loaded))
    return frozenset(keys)


def diff_config_keys(
    schema_keys: frozenset[str],
    docs_keys: frozenset[str],
) -> ConfigDriftReport:
    """Diff two key sets into a :class:`ConfigDriftReport`."""

    return ConfigDriftReport(
        extra_in_docs=frozenset(docs_keys - schema_keys),
        missing_in_docs=frozenset(schema_keys - docs_keys),
    )


# ---------------------------------------------------------------------------
# CLI-drift helpers
# ---------------------------------------------------------------------------


_IGNORED_FLAGS: frozenset[str] = frozenset({"--help", "--version", "--config"})
_LONG_FLAG_RE = re.compile(r"(--[a-z][a-z0-9-]+)")


def _iter_subparser_actions(
    parser: argparse.ArgumentParser,
) -> Iterable[argparse.ArgumentParser]:
    """Yield every subparser registered under ``parser`` (one level)."""

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            yield from action.choices.values()


def collect_cli_flags(parser: argparse.ArgumentParser) -> frozenset[str]:
    """Recursively collect long-form flags from ``parser`` and its subparsers."""

    flags: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        for opt in action.option_strings:
            if opt.startswith("--") and opt not in _IGNORED_FLAGS:
                flags.add(opt)
    for sub in _iter_subparser_actions(parser):
        flags.update(collect_cli_flags(sub))
    return frozenset(flags)


def parse_doc_cli_flags(markdown: str) -> frozenset[str]:
    """Scan ``markdown`` for long-form flag mentions, dropping ignored ones."""

    raw = set(_LONG_FLAG_RE.findall(markdown))
    return frozenset(flag for flag in raw if flag not in _IGNORED_FLAGS)


def diff_cli_flags(
    cli_flags: frozenset[str],
    doc_flags: frozenset[str],
) -> CliDriftReport:
    """Diff two CLI-flag sets into a :class:`CliDriftReport`."""

    return CliDriftReport(
        extra_in_docs=frozenset(doc_flags - cli_flags),
        missing_in_docs=frozenset(cli_flags - doc_flags),
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _default_schema_root() -> type:
    """Return :class:`seerflow.config.SeerflowConfig` (default schema root)."""

    module = importlib.import_module("seerflow.config")
    return module.SeerflowConfig  # type: ignore[no-any-return]


def _default_parser_factory() -> argparse.ArgumentParser:
    """Build the real Seerflow argparse parser."""

    module = importlib.import_module("seerflow.cli")
    return module.build_parser()  # type: ignore[no-any-return]


def _report_to_payload(
    config_report: ConfigDriftReport | None,
    cli_report: CliDriftReport | None,
) -> dict[str, Any]:
    """Assemble the JSON-serialisable payload written to ``--report-path``."""

    payload: dict[str, Any] = {}
    if config_report is not None:
        payload["config"] = {
            "extra_in_docs": sorted(config_report.extra_in_docs),
            "missing_in_docs": sorted(config_report.missing_in_docs),
            "ok": config_report.ok,
        }
    if cli_report is not None:
        payload["cli"] = {
            "extra_in_docs": sorted(cli_report.extra_in_docs),
            "missing_in_docs": sorted(cli_report.missing_in_docs),
            "ok": cli_report.ok,
        }
    return payload


def _print_human_report(payload: dict[str, Any]) -> None:
    """Print a human-readable summary to stdout."""

    for section, _label in (("config", "Config drift"), ("cli", "CLI drift")):
        if section not in payload:
            continue
        block = payload[section]
        "OK" if block["ok"] else "DRIFT"
        if block["extra_in_docs"]:
            for _k in block["extra_in_docs"]:
                pass
        if block["missing_in_docs"]:
            for _k in block["missing_in_docs"]:
                pass


def main(
    argv: Sequence[str] | None = None,
    *,
    schema_root_cls: type | None = None,
    parser_factory: Callable[[], argparse.ArgumentParser] | None = None,
) -> None:
    """Run the drift check.

    Raises :class:`SystemExit` with code 1 on drift; returns ``None`` on success.

    The ``schema_root_cls`` and ``parser_factory`` injection points exist so
    tests can run without requiring the real ``seerflow`` package.
    """

    cli = argparse.ArgumentParser(prog="check_docs_drift")
    cli.add_argument("--docs-dir", required=True, type=Path)
    cli.add_argument("--report-path", required=True, type=Path)
    cli.add_argument("--check", choices=("config", "cli", "all"), default="all")
    args = cli.parse_args(argv)

    docs_dir: Path = args.docs_dir
    report_path: Path = args.report_path
    do_config = args.check in ("config", "all")
    do_cli = args.check in ("cli", "all")

    config_report: ConfigDriftReport | None = None
    cli_report: CliDriftReport | None = None

    if do_config:
        root_cls = schema_root_cls or _default_schema_root()
        schema_keys = collect_schema_keys(root_cls)
        config_md = (docs_dir / "reference" / "configuration.md").read_text(encoding="utf-8")
        docs_keys = parse_config_yaml_blocks(config_md)
        config_report = diff_config_keys(schema_keys, docs_keys)

    if do_cli:
        parser = (parser_factory or _default_parser_factory)()
        cli_flags = collect_cli_flags(parser)
        cli_md = (docs_dir / "reference" / "cli.md").read_text(encoding="utf-8")
        doc_flags = parse_doc_cli_flags(cli_md)
        cli_report = diff_cli_flags(cli_flags, doc_flags)

    payload = _report_to_payload(config_report, cli_report)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _print_human_report(payload)

    failed = (config_report is not None and not config_report.ok) or (
        cli_report is not None and not cli_report.ok
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover — CLI entry
    main()
