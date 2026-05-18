"""Pure Markdown report renderer for LANL validation results.

``render_validation_report`` is a pure function: given a
:class:`~seerflow.lanl.validator.ValidationResult` and an explicit
date/label it returns deterministic Markdown. No I/O and no
``datetime.now()`` so the output is stable and testable. The optional
``__main__`` block runs the full S-045 harness and writes/prints the
report on demand (the Markdown file itself is not a committed artifact
because ``docs/`` is git-excluded).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.lanl.validator import ValidationResult

# Static prose for the three known synthetic-fixture attack scenarios.
_ATTACK_PATTERNS = """## Attack Patterns Detected

### 1. Brute-Force + Lateral Movement

- **Rule:** `brute-force-lateral-movement` (entity_type: user, window: 600s)
- **Scenario:** Red-team user U5624 -- auth failures followed by a success (C17693 -> C528)
- **MITRE:** T1110 (Brute Force), T1021 (Remote Services)

### 2. Credential Stuffing

- **Rule:** `credential-stuffing` (entity_type: ip, window: 300s)
- **Scenario:** Host C17693 generates 10+ auth failures across accounts
- **MITRE:** T1110.004 (Credential Stuffing)

### 3. C2 Beaconing

- **Rule:** `c2-beaconing` (entity_type: ip, window: 1800s)
- **Scenario:** Host C9999 makes periodic outbound connections to C8888:443
- **MITRE:** T1071 (Application Layer Protocol)
"""

_REPRODUCIBILITY = """## Reproducibility

Regenerate this report (against the committed synthetic fixtures):

```bash
uv run pytest tests/integration/test_lanl_validation.py -v
uv run python -m seerflow.lanl.report
```

## Run on the full LANL dataset

The committed fixtures are a ~200-event synthetic subset. To validate
against the full LANL Unified Host and Network Dataset:

1. Download the dataset from
   <https://csr.lanl.gov/data/unified-host-network-dataset-2017/>.
2. Unpack so a single directory contains `auth.csv`, `proc.csv`,
   `flows.csv`, and `redteam.csv` (the harness reads exactly these four).
3. Run:

   ```python
   from pathlib import Path
   from seerflow.lanl.validator import run_validation
   from seerflow.lanl.report import render_validation_report

   result = run_validation(Path("/path/to/lanl"))
   print(render_validation_report(
       result, dataset_label="full LANL Unified Host & Network Dataset",
       date="YYYY-MM-DD",
   ))
   ```

The harness is dataset-agnostic by construction -- only the directory
path changes.
"""


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_validation_report(
    result: ValidationResult,
    *,
    dataset_label: str,
    date: str,
) -> str:
    """Render a deterministic Markdown validation report.

    Args:
        result: Metrics produced by ``run_validation``.
        dataset_label: Human label for the dataset (e.g.
            ``"synthetic LANL subset"``). Echoed verbatim so consumers
            cannot misread synthetic numbers as full-dataset results.
        date: ISO date string (injected -- never ``datetime.now()``).

    Returns:
        The full Markdown report as a single string.
    """
    patterns = sorted(result.patterns_detected)
    latency_rows = "\n".join(
        f"| {rule} | {latency:.1f} |"
        for rule, latency in sorted(result.detection_latency_s.items())
    )
    family_rows = (
        "\n".join(
            f"| {fam} | {m.true_positives} | {m.false_positives} | "
            f"{_pct(m.precision)} | {_pct(m.f1_score)} |"
            for fam, m in sorted(result.per_family.items())
        )
        or "| (none fired) | 0 | 0 | 0.00% | 0.00% |"
    )

    return f"""# LANL Full-Stack Validation Report

**Date:** {date}
**Story:** S-305 -- full-pipeline LANL validation (FR-073)
**Dataset:** {dataset_label}
**Scope:** {result.scope_label}

## Summary

The Seerflow **full detection stack** (Drain3 -> ML ensemble -> Sigma ->
UEBA -> IoC -> correlation -- the identical `seerflow start` wiring via
`assemble_handler`) was run against the {dataset_label}. These numbers
describe the shipped product, not a correlation-only shortcut. On this
small synthetic subset, online/cold-start detectors (ML/UEBA) may emit no
alerts -- the per-family table below makes that explicit and honest.

## Results

| Metric | Value |
|--------|-------|
| Patterns detected | {len(patterns)} ({", ".join(patterns)}) |
| True positives | {result.true_positives} |
| False positives | {result.false_positives} |
| False negatives | {result.false_negatives} |
| Precision | {_pct(result.precision)} |
| Recall | {_pct(result.recall)} |
| F1 score | {_pct(result.f1_score)} |
| False-positive rate | {_pct(result.false_positive_rate)} |
| Total events processed | {result.total_events_processed} |
| Total alerts generated | {result.total_alerts} |

## Detection by Family

| Family | TP | FP | Precision | F1 |
|--------|----|----|-----------|----|
{family_rows}

## Detection Latency

| Rule | Avg Latency (seconds) |
|------|-----------------------|
{latency_rows}

{_ATTACK_PATTERNS}
## Limitations

1. **Synthetic subset:** the committed fixtures are a small synthetic
   dataset (~200 events) mimicking LANL format, not the full 1.05B-event
   dataset. Run on a downloaded full-dataset directory for headline numbers.
2. **Cold-start online detectors:** ML/UEBA are streaming learners; on a
   ~200-event subset they warm up but rarely fire. Absent ML/UEBA rows in
   the per-family table reflect this, not a wiring gap (the regression test
   `tests/integration/test_lanl_full_stack_regression.py` guards the wiring).
3. **Anonymized process names:** LANL anonymizes processes, so the
   privilege-escalation-chain rule cannot fire.
4. **Synthetic host-to-IP mapping:** real-world validation would use
   actual IP addresses.

{_REPRODUCIBILITY}"""


def _main(argv: list[str]) -> int:
    from pathlib import Path

    from seerflow.lanl.validator import run_validation

    fixtures = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "lanl"
    result = run_validation(fixtures)
    md = render_validation_report(
        result,
        dataset_label="synthetic LANL subset (tests/fixtures/lanl)",
        date="generated",
    )
    if len(argv) > 1:
        Path(argv[1]).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
