"""CLI handler for ``seerflow rules list``.

Loads bundled + custom Sigma rules without starting the pipeline and
prints them with optional MITRE ATT&CK filtering.
"""
# ruff: noqa: T201 — print() is the CLI output mechanism.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import msgspec.json

from seerflow.cli_format import format_table
from seerflow.sigma.attack import (
    TACTIC_IDS,
    TACTICS,
    is_valid_technique,
    resolve_tactic,
)
from seerflow.sigma.engine import SigmaEngine

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterable

    from seerflow.sigma.matcher import CompiledRule


def _rules_from_engine(engine: SigmaEngine) -> list[CompiledRule]:
    """Return all compiled rules loaded in the engine as a list."""
    return list(engine.iter_compiled_rules())


def _matches_technique(rule: CompiledRule, technique: str) -> bool:
    """True if any of the rule's techniques equals ``technique`` or is a sub-technique."""
    prefix = technique + "."
    for t in rule.attack_techniques:
        t_up = t.upper()
        if t_up == technique or t_up.startswith(prefix):
            return True
    return False


def _apply_filters(
    rules: Iterable[CompiledRule],
    *,
    technique: str | None,
    tactic_name: str | None,
) -> list[CompiledRule]:
    """Return rules that match every provided filter. None → no filter."""
    result: list[CompiledRule] = []
    for rule in rules:
        if technique is not None and not _matches_technique(rule, technique):
            continue
        if tactic_name is not None and tactic_name not in rule.attack_tactics:
            continue
        result.append(rule)
    return result


def _format_logsource(logsource: tuple[str, str, str]) -> str:
    """Render logsource tuple as ``product/category/service`` with empty parts elided.

    The tuple layout is ``(category, product, service)`` (matching
    ``CompiledRule.logsource_key``), but the display order puts product first
    to mirror the SigmaHQ rule-path convention (``windows/process_creation``).
    """
    category, product, service = logsource
    parts = [p for p in (product, category, service) if p]
    return "/".join(parts) if parts else "-"


def run_rules_list(args: argparse.Namespace) -> int:
    """Execute ``seerflow rules list`` and return the process exit code."""
    technique: str | None = None
    if args.technique is not None:
        raw = args.technique.strip()
        if not is_valid_technique(raw):
            print(
                f"Error: invalid technique '{args.technique}'. "
                "Expected format: T#### or T####.### (e.g., T1053 or T1053.005)",
                file=sys.stderr,
            )
            return 2
        technique = raw.upper()

    tactic_name: str | None = None
    if args.tactic is not None:
        resolved = resolve_tactic(args.tactic)
        if resolved is None:
            valid = sorted(set(TACTICS) | set(TACTIC_IDS))
            print(
                f"Error: unknown tactic '{args.tactic}'. Valid values: {', '.join(valid)}",
                file=sys.stderr,
            )
            return 2
        tactic_name = resolved

    sigma_dirs: tuple[str, ...] = ()
    try:
        from seerflow.config import ConfigError, load_config

        cfg = load_config(args.config)
        sigma_dirs = cfg.detection.sigma_rules_dirs
    except FileNotFoundError:
        sigma_dirs = ()
    except ConfigError as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    engine = SigmaEngine()
    engine.load_bundled()
    if sigma_dirs:
        engine.load_custom(sigma_dirs)

    rules = _rules_from_engine(engine)
    total = len(rules)
    filter_active = technique is not None or tactic_name is not None
    filtered = _apply_filters(rules, technique=technique, tactic_name=tactic_name)

    if args.format == "json":
        _print_json(filtered)
    else:
        _print_table(filtered, total=total, filter_active=filter_active)
    return 0


def _print_json(rules: list[CompiledRule]) -> None:
    payload = [
        {
            "name": r.rule_name,
            "severity": r.severity.name,
            "logsource": {
                "category": r.logsource_key[0],
                "product": r.logsource_key[1],
                "service": r.logsource_key[2],
            },
            "tactics": list(r.attack_tactics),
            "techniques": list(r.attack_techniques),
            "description": r.description,
        }
        for r in rules
    ]
    sys.stdout.buffer.write(msgspec.json.encode(payload))
    print()


def _print_table(rules: list[CompiledRule], *, total: int, filter_active: bool) -> None:
    if total == 0:
        print("No rules loaded.")
        return

    headers = ["NAME", "SEVERITY", "LOGSOURCE", "TACTICS", "TECHNIQUES"]
    rows = [
        [
            r.rule_name,
            r.severity.name,
            _format_logsource(r.logsource_key),
            ", ".join(r.attack_tactics) or "-",
            ", ".join(r.attack_techniques) or "-",
        ]
        for r in rules
    ]
    print(format_table(headers, rows), end="")
    if filter_active:
        print(f"\n{total} rules loaded, {len(rules)} matching filter")
    else:
        print(f"\n{total} rules loaded")


__all__ = ["run_rules_list"]
