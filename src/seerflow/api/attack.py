"""Pure functions for ATT&CK coverage matrix construction.

No HTTP, storage, or FastAPI dependencies. These functions take engine
and rule snapshots plus an alert iterable and return a fully-formed
``AttackCoverageResponse``. Unit-testable in isolation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from seerflow.api.schemas import (
    AttackCoverageCell,
    AttackCoverageResponse,
    AttackCoverageSummary,
    AttackCoverageTactic,
)
from seerflow.sigma.attack import TACTICS, format_tactic, format_technique

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from seerflow.models.alert import Alert, CorrelationRule
    from seerflow.sigma.engine import SigmaEngine

CellKey = tuple[str, str]  # (tactic_raw, technique_uppercase)


def collect_sigma_cells(engine: SigmaEngine | None) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per Sigma rule."""
    counts: dict[CellKey, int] = defaultdict(int)
    if engine is None:
        return counts
    for rule in engine.iter_compiled_rules():
        if not rule.attack_tactics or not rule.attack_techniques:
            continue
        for tactic in rule.attack_tactics:
            if not tactic:
                continue
            for technique in rule.attack_techniques:
                if not technique:
                    continue
                counts[(tactic, format_technique(technique))] += 1
    return counts


def collect_correlation_cells(
    rules: Sequence[CorrelationRule],
) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per correlation rule."""
    counts: dict[CellKey, int] = defaultdict(int)
    for rule in rules:
        if not rule.mitre_tactics or not rule.mitre_techniques:
            continue
        for tactic in rule.mitre_tactics:
            if not tactic:
                continue
            for technique in rule.mitre_techniques:
                if not technique:
                    continue
                counts[(tactic, format_technique(technique))] += 1
    return counts


def collect_alert_cells(alerts: Iterable[Alert]) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per alert."""
    counts: dict[CellKey, int] = defaultdict(int)
    for alert in alerts:
        if not alert.mitre_tactics or not alert.mitre_techniques:
            continue
        for tactic in alert.mitre_tactics:
            if not tactic:
                continue
            for technique in alert.mitre_techniques:
                if not technique:
                    continue
                counts[(tactic, format_technique(technique))] += 1
    return counts


def _cells_for_tactic(
    keys: list[CellKey],
    rule_counts: dict[CellKey, int],
    alert_counts: dict[CellKey, int],
) -> list[AttackCoverageCell]:
    cells: list[AttackCoverageCell] = []
    for key in keys:
        rc = rule_counts.get(key, 0)
        ac = alert_counts.get(key, 0)
        cells.append(
            AttackCoverageCell(
                tactic=key[0],
                technique=key[1],
                rule_count=rc,
                alert_count=ac,
                covered=rc > 0,
                detected=ac > 0,
            )
        )
    return cells


def build_matrix(
    rule_counts: dict[CellKey, int],
    alert_counts: dict[CellKey, int],
    *,
    window_since: datetime,
    window_until: datetime,
) -> AttackCoverageResponse:
    """Merge rule and alert counts into a stable-ordered coverage response."""
    by_tactic: dict[str, list[CellKey]] = defaultdict(list)
    all_keys = set(rule_counts) | set(alert_counts)
    for key in sorted(all_keys):
        by_tactic[key[0]].append(key)

    tactics: list[AttackCoverageTactic] = []
    known = list(TACTICS.keys())
    known_set = set(known)

    for tactic in known:
        tactics.append(
            AttackCoverageTactic(
                tactic=tactic,
                tactic_display_name=format_tactic(tactic),
                techniques=_cells_for_tactic(by_tactic.get(tactic, []), rule_counts, alert_counts),
            )
        )

    for tactic in sorted(t for t in by_tactic if t not in known_set):
        tactics.append(
            AttackCoverageTactic(
                tactic=tactic,
                tactic_display_name=format_tactic(tactic),
                techniques=_cells_for_tactic(by_tactic[tactic], rule_counts, alert_counts),
            )
        )

    total_covered = sum(1 for t in tactics for c in t.techniques if c.covered)
    total_detected = sum(1 for t in tactics for c in t.techniques if c.detected)

    return AttackCoverageResponse(
        window_since=window_since.isoformat(),
        window_until=window_until.isoformat(),
        tactics=tactics,
        summary=AttackCoverageSummary(
            total_techniques_covered=total_covered,
            total_techniques_detected=total_detected,
            total_rules_with_attack_tags=sum(rule_counts.values()),
            total_alerts_matched=sum(alert_counts.values()),
        ),
    )
