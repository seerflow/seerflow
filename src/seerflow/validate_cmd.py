"""``seerflow validate`` — surface the LANL accuracy harness from the CLI (S-307).

Wraps the read-only ``seerflow.lanl.validator.run_validation`` seam (S-305).
AUC over a score-threshold sweep is FR-079 (S-309) and is intentionally
``null`` here; MTTD is derived as the mean per-rule detection latency.
"""
# ruff: noqa: T201 -- print() is the CLI output mechanism.

from __future__ import annotations

import statistics
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec.json

from seerflow.cli_format import format_table

if TYPE_CHECKING:
    import argparse

    from seerflow.lanl.validator import ValidationResult

_AUC_NOTE = (
    "AUC over a score-threshold sweep is delivered by FR-079 (S-309); "
    "not computed by run_validation."
)

EXIT_OK = 0
EXIT_USAGE = 2


class _UsageError(Exception):
    """Raised for an operator input error; mapped to exit code 2."""


def _mttd_seconds(detection_latency_s: dict[str, float]) -> float:
    """Mean detection latency (seconds) across rules; 0.0 when empty."""
    if not detection_latency_s:
        return 0.0
    return statistics.fmean(detection_latency_s.values())


def _result_to_dict(result: ValidationResult, *, dataset_dir: str) -> dict[str, object]:
    """Build the deterministic machine-readable metric document.

    ``auc`` is ``None`` by design (FR-079/S-309 owns the real value);
    ``mttd_seconds`` is the mean of per-rule detection latencies.
    """
    return {
        "precision": result.precision,
        "recall": result.recall,
        "f1": result.f1_score,
        "false_positive_rate": result.false_positive_rate,
        "mttd_seconds": _mttd_seconds(result.detection_latency_s),
        "auc": None,
        "auc_note": _AUC_NOTE,
        "true_positives": result.true_positives,
        "false_positives": result.false_positives,
        "false_negatives": result.false_negatives,
        "total_events_processed": result.total_events_processed,
        "total_alerts": result.total_alerts,
        "patterns_detected": sorted(result.patterns_detected),
        "dataset_dir": dataset_dir,
    }
