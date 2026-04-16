"""Pure functions for ATT&CK coverage matrix construction.

No HTTP, storage, or FastAPI dependencies. These functions take engine
and rule snapshots plus an alert iterable and return a fully-formed
``AttackCoverageResponse``. Unit-testable in isolation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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


@dataclass(frozen=True)
class CellData:
    """Aggregated rule data for one (tactic, technique) cell."""

    count: int = 0
    rule_names: tuple[str, ...] = ()

    def add(self, name: str) -> CellData:
        new_names = (*self.rule_names, name) if name else self.rule_names
        return CellData(count=self.count + 1, rule_names=new_names)


def _collect_tag_pairs(
    tactics: tuple[str, ...],
    techniques: tuple[str, ...],
    cells: dict[CellKey, CellData],
    rule_name: str = "",
) -> None:
    """Add rule_name to ``cells`` for every valid (tactic, technique) pair.

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
            key = (tactic, format_technique(technique))
            existing = cells.get(key, CellData())
            cells[key] = existing.add(rule_name)


def collect_sigma_cells(engine: SigmaEngine | None) -> dict[CellKey, CellData]:
    """Collect one CellData per (tactic, technique) pair per Sigma rule."""
    cells: dict[CellKey, CellData] = {}
    if engine is None:
        return cells
    for rule in engine.iter_compiled_rules():
        _collect_tag_pairs(rule.attack_tactics, rule.attack_techniques, cells, rule.rule_name)
    return cells


def collect_correlation_cells(
    rules: Sequence[CorrelationRule],
) -> dict[CellKey, CellData]:
    """Collect one CellData per (tactic, technique) pair per correlation rule."""
    cells: dict[CellKey, CellData] = {}
    for rule in rules:
        _collect_tag_pairs(rule.mitre_tactics, rule.mitre_techniques, cells, rule.name)
    return cells


def collect_alert_cells(alerts: Iterable[Alert]) -> dict[CellKey, CellData]:
    """Count one hit per (tactic, technique) pair per alert.

    Alerts contribute to cell counts but do not carry rule names into the cell.
    """
    cells: dict[CellKey, CellData] = {}
    for alert in alerts:
        _collect_tag_pairs(alert.mitre_tactics, alert.mitre_techniques, cells)
    return cells


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


def merge_rule_data(
    *sources: dict[CellKey, CellData],
) -> dict[CellKey, CellData]:
    """Merge multiple CellData dicts, summing counts and concatenating rule names."""
    merged: dict[CellKey, CellData] = {}
    for source in sources:
        for key, data in source.items():
            existing = merged.get(key, CellData())
            merged[key] = CellData(
                count=existing.count + data.count,
                rule_names=(*existing.rule_names, *data.rule_names),
            )
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
