"""LANL benchmark baselines registry loader (S-358).

``load_baselines`` reads a YAML list of baseline rows and returns validated
:class:`~seerflow.lanl.report.schema.Baseline` instances.  Validation is
strict: any row that fails the schema contract (unknown metric, bad kind/
comparison, non-numeric or ``None`` value, empty/missing source) raises
:class:`ValueError` immediately so the registry cannot be used in a half-
populated state.

The packaged ``baselines.yaml`` ships with a ``value: null`` placeholder row
for unresolved published baselines (S-358 Task 3).  That placeholder
intentionally triggers the numeric-value check, making ``load_baselines()``
raise until the research pass populates real values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast, get_args

import yaml

from seerflow.lanl.report.schema import Baseline, BaselineKind, Comparison

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_BASELINES_PATH: Path = Path(__file__).parent / "baselines.yaml"

_KNOWN_METRICS: frozenset[str] = frozenset(
    {
        "precision",
        "recall",
        "f1",
        "auc",
        "false_positive_rate",
        "true_positives",
        "false_positives",
        "false_negatives",
    }
)

# Single source of truth: derive from the schema ``Literal`` aliases so the
# loader's allow-lists cannot drift from the type definitions.
_KNOWN_KINDS: frozenset[str] = frozenset(get_args(BaselineKind))
_KNOWN_COMPARISONS: frozenset[str] = frozenset(get_args(Comparison))


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _validate_row(row: Any, index: int) -> Baseline:
    """Validate a single parsed YAML mapping and return a :class:`Baseline`.

    Args:
        row:   The raw mapping from ``yaml.safe_load``.
        index: Zero-based row index (used in error messages).

    Returns:
        A validated, frozen :class:`Baseline` instance.

    Raises:
        ValueError: If any field violates the schema contract.
    """
    if not isinstance(row, dict):
        raise ValueError(f"baselines[{index}]: expected a mapping, got {type(row).__name__!r}")

    metric = row.get("metric", "")
    if not isinstance(metric, str) or metric not in _KNOWN_METRICS:
        raise ValueError(
            f"baselines[{index}]: unknown metric {metric!r}; allowed: {sorted(_KNOWN_METRICS)}"
        )

    kind = row.get("kind", "")
    if not isinstance(kind, str) or kind not in _KNOWN_KINDS:
        raise ValueError(
            f"baselines[{index}]: invalid kind {kind!r}; allowed: {sorted(_KNOWN_KINDS)}"
        )

    comparison = row.get("comparison", "")
    if not isinstance(comparison, str) or comparison not in _KNOWN_COMPARISONS:
        raise ValueError(
            f"baselines[{index}]: invalid comparison {comparison!r}; "
            f"allowed: {sorted(_KNOWN_COMPARISONS)}"
        )

    raw_value = row.get("value")
    if raw_value is None or not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
        raise ValueError(
            f"baselines[{index}]: value must be a numeric float/int, "
            f"got {raw_value!r} (type {type(raw_value).__name__!r}); "
            "null values indicate an unresolved published baseline"
        )
    value: float = float(raw_value)

    source = row.get("source", "")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"baselines[{index}]: source must be a non-empty string, got {source!r}")

    notes: str | None = row.get("notes")
    if notes is not None and not isinstance(notes, str):
        notes = str(notes)

    return Baseline(
        # kind/comparison are validated against the known sets above, so the
        # casts are sound; they narrow ``str`` to the schema Literal aliases.
        metric=metric,
        kind=cast("BaselineKind", kind),
        value=value,
        comparison=cast("Comparison", comparison),
        source=source,
        notes=notes if notes else None,
    )


def load_baselines(path: Path | None = None) -> list[Baseline]:
    """Load and validate baselines from a YAML file.

    Args:
        path: Path to a YAML file containing a list of baseline rows.
              Defaults to the packaged ``baselines.yaml``.

    Returns:
        A list of validated :class:`~seerflow.lanl.report.schema.Baseline`
        instances.

    Raises:
        ValueError: If any row violates the schema contract — unknown metric,
                    invalid kind or comparison, non-numeric/``None`` value, or
                    empty/missing source.
        FileNotFoundError: If ``path`` does not exist.
    """
    resolved = path if path is not None else _DEFAULT_BASELINES_PATH
    raw_text = resolved.read_text(encoding="utf-8")
    raw_data = yaml.safe_load(raw_text)

    if not isinstance(raw_data, list):
        raise ValueError(f"baselines YAML must be a list, got {type(raw_data).__name__!r}")

    return [_validate_row(row, idx) for idx, row in enumerate(raw_data)]
