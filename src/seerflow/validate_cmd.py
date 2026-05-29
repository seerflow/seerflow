"""``seerflow validate`` — surface the LANL accuracy harness from the CLI.

Wraps the read-only ``seerflow.lanl.validator.run_validation`` seam (S-305)
and emits the S-311 / FR-079 attack-level metrics: real AUC over a
risk-score threshold sweep, per-attack-scenario mean-time-to-detect,
precision-recall + ROC curves, and the silent detector family for every
missed red-team event. The document is deterministic and msgspec-encodable
so ``--json`` is consumable with no Python required (FR-075).
"""
# ruff: noqa: T201 -- print() is the CLI output mechanism.

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from seerflow.cli_format import emit_doc

if TYPE_CHECKING:
    import argparse

    from seerflow.lanl.validator import ValidationResult

EXIT_OK = 0
EXIT_USAGE = 2


class _UsageError(Exception):
    """Raised for an operator input error; mapped to exit code 2."""


def _scenario_doc(result: ValidationResult) -> list[dict[str, object]]:
    """Per-attack-scenario rows: name, MTTD (``None`` if undetected), counts."""
    return [
        {
            "name": s.name,
            "first_event_time_s": s.first_event_time_s,
            "record_count": s.record_count,
            "detected": s.detected,
            "mttd_seconds": s.mttd_seconds,
            "missed_record_count": s.missed_record_count,
        }
        for s in result.attack_scenarios
    ]


def _missed_doc(result: ValidationResult) -> list[dict[str, object]]:
    """Silent-family attribution rows for every missed red-team record."""
    return [
        {
            "record": m.record_repr,
            "scenario": m.scenario_name,
            "silent_family": m.silent_family,
        }
        for m in result.missed_attributions
    ]


def _result_to_dict(result: ValidationResult, *, dataset_dir: str) -> dict[str, object]:
    """Build the deterministic machine-readable metric document (FR-079).

    ``auc`` is the real trapezoidal area under the swept ROC curve (``None``
    only when there were zero alerts and zero red-team events); MTTD is
    reported *per attack scenario* (not a flat per-rule latency mean — the
    S-307 placeholder that this story removes).
    """
    return {
        "precision": result.precision,
        "recall": result.recall,
        "f1": result.f1_score,
        "false_positive_rate": result.false_positive_rate,
        "auc": result.auc,
        "attack_scenarios": _scenario_doc(result),
        "pr_points": [list(p) for p in result.pr_points],
        "roc_points": [list(p) for p in result.roc_points],
        "missed_attributions": _missed_doc(result),
        "true_positives": result.true_positives,
        "false_positives": result.false_positives,
        "false_negatives": result.false_negatives,
        "total_events_processed": result.total_events_processed,
        "total_alerts": result.total_alerts,
        "patterns_detected": sorted(result.patterns_detected),
        "dataset_dir": dataset_dir,
    }


def _validate_dataset_dir(raw: str) -> Path:
    """Resolve ``raw`` and confirm it is an existing directory.

    Raises ``_UsageError`` (mapped to exit code 2) otherwise. The accuracy
    harness is never invoked on a bad path.
    """
    path = Path(raw)
    if not path.is_dir():
        msg = f"dataset directory not found: {raw}"
        raise _UsageError(msg)
    return path


def run_validate(args: argparse.Namespace) -> int:
    """``seerflow validate`` entry point. Returns a process exit code."""
    try:
        dataset = _validate_dataset_dir(args.dataset_dir)
    except _UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    from seerflow.lanl.validator import run_validation

    result = run_validation(dataset)
    doc = _result_to_dict(result, dataset_dir=str(dataset))
    emit_doc(doc, as_json=bool(args.json))
    return EXIT_OK


__all__ = ["run_validate"]
