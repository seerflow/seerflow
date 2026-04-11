"""Pure functions for ATT&CK coverage matrix construction.

No HTTP, storage, or FastAPI dependencies. These functions take engine
and rule snapshots plus an alert iterable and return a fully-formed
``AttackCoverageResponse``. Unit-testable in isolation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, TypeAlias

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

CellKey: TypeAlias = tuple[str, str]  # (tactic_raw, technique_uppercase)


def _count_tag_pairs(
    tactics: tuple[str, ...],
    techniques: tuple[str, ...],
    counts: dict[CellKey, int],
) -> None:
    """Increment ``counts`` for every valid (tactic, technique) pair.

    Drops empty-string entries and pairs where either tuple is empty.
    Techniques are normalized with ``format_technique`` before keying.
    """
    if not tactics or not techniques:
        return
    for tactic in tactics:
        if not tactic:
            continue
        for technique in techniques:
            if not technique:
                continue
            counts[(tactic, format_technique(technique))] += 1


def collect_sigma_cells(engine: SigmaEngine | None) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per Sigma rule."""
    counts: dict[CellKey, int] = defaultdict(int)
    if engine is None:
        return counts
    for rule in engine.iter_compiled_rules():
        _count_tag_pairs(rule.attack_tactics, rule.attack_techniques, counts)
    return counts


def collect_correlation_cells(
    rules: Sequence[CorrelationRule],
) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per correlation rule."""
    counts: dict[CellKey, int] = defaultdict(int)
    for rule in rules:
        _count_tag_pairs(rule.mitre_tactics, rule.mitre_techniques, counts)
    return counts


def collect_alert_cells(alerts: Iterable[Alert]) -> dict[CellKey, int]:
    """Count one hit per (tactic, technique) pair per alert."""
    counts: dict[CellKey, int] = defaultdict(int)
    for alert in alerts:
        _count_tag_pairs(alert.mitre_tactics, alert.mitre_techniques, counts)
    return counts


def merge_rule_counts(
    *sources: dict[CellKey, int],
) -> dict[CellKey, int]:
    """Merge multiple rule-count dicts into one.

    The route handler collects counts from the Sigma engine and the
    correlation-rules list separately, then merges here. Keeping the
    merge in this pure module prevents the route from growing merge
    logic when new rule sources are added.
    """
    merged: dict[CellKey, int] = defaultdict(int)
    for source in sources:
        for key, count in source.items():
            merged[key] += count
    return merged


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
    known_set = set(TACTICS)

    for tactic in TACTICS:
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
