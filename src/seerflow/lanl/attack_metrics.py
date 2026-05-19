"""Attack-level detection metrics for the LANL harness (S-311 / FR-079).

Pure, deterministic post-hoc scoring over the *already-matched* alert set
and the *already-rebased* red-team records that
:mod:`seerflow.lanl.validator` produces. No I/O, no ``time.time_ns()``, no
set-iteration-order leakage — every output is a pure function of its inputs
so two runs on the same fixtures are byte-identical (NFR-013 / NFR-017).

Provides, per FR-079:

* :func:`group_scenarios` — cluster ``RedTeamRecord``\\ s into the three
  documented synthetic attack scenarios (plus a stable ``"other"`` bucket).
* :func:`scenario_mttd` — per-scenario mean-time-to-detect (first covering
  true-positive alert minus the scenario's first ground-truth event), or
  ``None`` when the scenario was never detected (never silently ``0.0``).
* :func:`threshold_sweep` — precision-recall + ROC point lists over a
  deterministic alert ``risk_score`` threshold sweep.
* :func:`roc_auc` — trapezoidal area under the swept ROC curve.
* :func:`attribute_missed` — for each missed red-team record, the silent
  detector family that should have caught it (explicit data-table map).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerflow.lanl.parser import RedTeamRecord
    from seerflow.models.alert import Alert

# Explicit scenario -> silent-detector-family map. The committed synthetic
# subset's red-team activity is correlation-detectable by construction
# (ML/UEBA cold-start on ~200 events); a downloaded full dataset would
# extend this table (out of scope here). A data table, not a heuristic, so
# it is deterministic and unit-testable.
_SCENARIO_FAMILY: dict[str, str] = {
    "brute-force-lateral-movement": "correlation",
    "credential-stuffing": "correlation",
    "c2-beaconing": "correlation",
    "other": "correlation",
}


@dataclass(frozen=True, slots=True)
class AttackScenarioMetrics:
    """Per-red-team-scenario detection sub-metrics.

    ``mttd_seconds`` is ``None`` when the scenario produced no covering true
    positive — distinct from a genuine instant (0.0 s) detection so a
    downstream mean cannot be silently corrupted.
    """

    name: str
    first_event_time_s: int
    record_count: int
    detected: bool
    mttd_seconds: float | None
    missed_record_count: int


@dataclass(frozen=True, slots=True)
class MissedAttribution:
    """A missed red-team record and the silent detector family for it."""

    record_repr: str
    scenario_name: str
    silent_family: str


# ---------------------------------------------------------------------------
# Scenario grouping
# ---------------------------------------------------------------------------


def classify_scenario(rec: RedTeamRecord) -> str:
    """Map one red-team record to its documented scenario name.

    Static, deterministic classification against the three synthetic-fixture
    attack patterns (``report.py::_ATTACK_PATTERNS``):

    * anonymized user (``"?"``) repeating ``C9999 -> C8888`` -> C2 beaconing
    * source host ``C17693`` lateral hop with a single user -> brute-force
    * source host ``C17693`` fanning across multiple users -> cred stuffing
    """
    if rec.user == "?":
        return "c2-beaconing"
    if rec.src_computer == "C17693" and rec.dst_computer == "C528":
        return "brute-force-lateral-movement"
    if rec.src_computer == "C17693":
        return "credential-stuffing"
    return "other"


def group_scenarios(
    redteam_records: list[RedTeamRecord],
) -> tuple[AttackScenarioMetrics, ...]:
    """Group red-team records into named scenarios, deterministically.

    Returns a tuple sorted by ``(first_event_time_s, name)``. ``detected``
    and ``mttd_seconds`` are left at their "undetected" defaults here; the
    caller refines them via :func:`scenario_mttd` once alerts are known
    (keeps this function a pure function of the labels alone).
    """
    buckets: dict[str, list[RedTeamRecord]] = {}
    for rec in redteam_records:
        buckets.setdefault(classify_scenario(rec), []).append(rec)

    scenarios = [
        AttackScenarioMetrics(
            name=name,
            first_event_time_s=min(r.time for r in recs),
            record_count=len(recs),
            detected=False,
            mttd_seconds=None,
            missed_record_count=len(recs),
        )
        for name, recs in buckets.items()
    ]
    return tuple(sorted(scenarios, key=lambda s: (s.first_event_time_s, s.name)))


def _scenario_entities(name: str, redteam_records: list[RedTeamRecord]) -> set[str]:
    """Lowercased entity set (users + hosts + derived IPs) for a scenario."""
    import contextlib

    from seerflow.lanl.hostmap import host_to_ip
    from seerflow.models.entity import normalize_username

    entities: set[str] = set()
    for rec in redteam_records:
        if classify_scenario(rec) != name:
            continue
        if rec.user != "?":
            norm_user, _domain = normalize_username(rec.user)
            entities.add(norm_user)
        for host in (rec.src_computer, rec.dst_computer):
            entities.add(host.lower())
            with contextlib.suppress(ValueError, TypeError):
                entities.add(host_to_ip(host))
    return entities


def scenario_mttd(
    scenario: AttackScenarioMetrics,
    redteam_records: list[RedTeamRecord],
    tp_alerts: list[Alert],
) -> float | None:
    """Mean-time-to-detect for ``scenario`` in seconds, or ``None``.

    The "first covering alert" is the earliest true-positive alert whose
    ``entity_value`` is in the scenario's entity set. MTTD is that alert's
    timestamp minus the scenario's first ground-truth event time. ``None``
    when no alert covers the scenario (never silently ``0.0``).
    """
    entity_set = _scenario_entities(scenario.name, redteam_records)
    covering = [
        a.timestamp_ns // 1_000_000_000
        for a in tp_alerts
        if a.entity_value.lower().strip() in entity_set
    ]
    if not covering:
        return None
    return float(min(covering) - scenario.first_event_time_s)


# ---------------------------------------------------------------------------
# PR / ROC threshold sweep + trapezoidal AUC
# ---------------------------------------------------------------------------


def threshold_sweep(
    tp_alerts: list[Alert],
    fp_alerts: list[Alert],
    *,
    n_redteam: int,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[float, float, float], ...],
]:
    """Sweep the alert ``risk_score`` threshold; return PR + ROC point lists.

    Cut-points are ``sorted({0.0, 1.0} | {distinct risk scores})`` (explicit
    sort — no set-iteration order). At each threshold an alert counts toward
    TP/FP only if ``risk_score >= threshold``. Recall (= ROC ``tpr``)
    denominator is the fixed red-team count. There are no labelled negatives
    in an unsupervised alert stream, so ``fpr`` uses the total false-positive
    alert count at threshold 0 as the negatives proxy (a higher threshold can
    only reduce the FP numerator, so ``fpr`` is monotone non-increasing).
    Returns ``(pr_points, roc_points)`` as immutable sorted tuples of
    ``(threshold, precision, recall)`` / ``(threshold, fpr, tpr)``.
    """
    # Degenerate input (no alerts AND no ground truth) -> no curve at all,
    # so roc_auc() can return its None sentinel (AC2).
    if not tp_alerts and not fp_alerts and n_redteam == 0:
        return (), ()
    thresholds = sorted(
        {0.0, 1.0} | {a.risk_score for a in tp_alerts} | {a.risk_score for a in fp_alerts}
    )
    total_neg = len(fp_alerts)
    pr: list[tuple[float, float, float]] = []
    roc: list[tuple[float, float, float]] = []
    for thr in thresholds:
        tp = sum(1 for a in tp_alerts if a.risk_score >= thr)
        fp = sum(1 for a in fp_alerts if a.risk_score >= thr)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / n_redteam if n_redteam > 0 else 0.0
        fpr = fp / total_neg if total_neg > 0 else 0.0
        pr.append((thr, precision, recall))
        roc.append((thr, fpr, recall))
    return tuple(pr), tuple(roc)


def roc_auc(
    roc_points: tuple[tuple[float, float, float], ...],
) -> float | None:
    """Trapezoidal AUC over the ROC curve, clamped to ``[0.0, 1.0]``.

    ``None`` only when the sweep produced no curve (zero alerts AND zero
    red-team events). Points are sorted by ``(fpr, tpr)`` before
    integration so the area is independent of threshold order. A degenerate
    single-distinct-point curve yields a finite (possibly 0.0) area.
    """
    if not roc_points:
        return None
    pts = sorted((fpr, tpr) for _thr, fpr, tpr in roc_points)
    # Deduplicate identical (fpr, tpr) pairs to keep the integral stable.
    uniq: list[tuple[float, float]] = []
    for p in pts:
        if not uniq or uniq[-1] != p:
            uniq.append(p)
    area = 0.0
    for (x0, y0), (x1, y1) in itertools.pairwise(uniq):
        area += (x1 - x0) * (y0 + y1) / 2.0
    return max(0.0, min(1.0, area))


# ---------------------------------------------------------------------------
# Missed-event silent-family attribution
# ---------------------------------------------------------------------------


def _record_repr(rec: RedTeamRecord) -> str:
    """Stable string key for a red-team record (deterministic ordering)."""
    return f"{rec.time}|{rec.user}|{rec.src_computer}|{rec.dst_computer}"


def attribute_missed(
    missed_redteam: list[RedTeamRecord],
) -> tuple[MissedAttribution, ...]:
    """Name the silent detector family for each missed red-team record.

    Uses the explicit :data:`_SCENARIO_FAMILY` data-table map keyed by the
    record's classified scenario (the map is global and authoritative).
    Returns a tuple sorted by ``(scenario_name, record_repr)`` so the
    output is deterministic; every missed record appears exactly once.
    """
    attrs = [
        MissedAttribution(
            record_repr=_record_repr(rec),
            scenario_name=classify_scenario(rec),
            silent_family=_SCENARIO_FAMILY[classify_scenario(rec)],
        )
        for rec in missed_redteam
    ]
    return tuple(sorted(attrs, key=lambda m: (m.scenario_name, m.record_repr)))


__all__ = [
    "AttackScenarioMetrics",
    "MissedAttribution",
    "attribute_missed",
    "classify_scenario",
    "group_scenarios",
    "roc_auc",
    "scenario_mttd",
    "threshold_sweep",
]
