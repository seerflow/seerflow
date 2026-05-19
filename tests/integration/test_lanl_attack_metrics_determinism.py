"""S-311 / FR-079 determinism + S-305 no-regression guard.

AC4: two ``run_validation`` runs on the committed synthetic fixtures must
produce byte-identical attack-level metrics (scenarios, PR/ROC points,
AUC, missed attributions). AC5: the S-305 headline tuple
(precision/recall/F1/FPR + counts) must be unchanged by the additive
S-311 fields. The metrics are pure functions of the deterministic,
clock-frozen replay S-305 established, so equality is exact (no tolerance).
"""

from __future__ import annotations

from pathlib import Path

import msgspec.json

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


def _attack_blob(r: object) -> bytes:
    """msgspec-encoded view of just the S-311 attack-level fields."""
    return msgspec.json.encode(
        {
            "auc": r.auc,  # type: ignore[attr-defined]
            "scenarios": [
                (
                    s.name,
                    s.first_event_time_s,
                    s.record_count,
                    s.detected,
                    s.mttd_seconds,
                    s.missed_record_count,
                )
                for s in r.attack_scenarios  # type: ignore[attr-defined]
            ],
            "pr_points": [list(p) for p in r.pr_points],  # type: ignore[attr-defined]
            "roc_points": [list(p) for p in r.roc_points],  # type: ignore[attr-defined]
            "missed": [
                (m.record_repr, m.scenario_name, m.silent_family)
                for m in r.missed_attributions  # type: ignore[attr-defined]
            ],
        }
    )


def _headline(r: object) -> tuple[float, ...]:
    return (
        r.precision,  # type: ignore[attr-defined]
        r.recall,  # type: ignore[attr-defined]
        r.f1_score,  # type: ignore[attr-defined]
        r.false_positive_rate,  # type: ignore[attr-defined]
        float(r.true_positives),  # type: ignore[attr-defined]
        float(r.false_positives),  # type: ignore[attr-defined]
        float(r.false_negatives),  # type: ignore[attr-defined]
        float(r.total_alerts),  # type: ignore[attr-defined]
        float(r.total_events_processed),  # type: ignore[attr-defined]
    )


def test_attack_metrics_byte_identical_across_runs() -> None:
    from seerflow.lanl.validator import run_validation

    r1 = run_validation(FIXTURES_DIR)
    r2 = run_validation(FIXTURES_DIR)
    assert _attack_blob(r1) == _attack_blob(r2)


def test_attack_metrics_do_not_perturb_s305_headline() -> None:
    """AC5: additive fields must not move the published headline numbers.

    The frozen golden mirrors the S-305 determinism baseline
    (P=2/12=16.67%, R=2/6=33.33%, 12 alerts / 137 events).
    """
    from seerflow.lanl.validator import run_validation

    r = run_validation(FIXTURES_DIR)
    h = _headline(r)
    assert h[0] == 2 / 12  # precision
    assert h[1] == 2 / 6  # recall
    assert h[4] == 2.0  # TP
    assert h[5] == 10.0  # FP
    assert h[6] == 4.0  # FN
    assert h[7] == 12.0  # total alerts
    assert h[8] == 137.0  # events processed


def test_auc_is_finite_and_bounded() -> None:
    from seerflow.lanl.validator import run_validation

    r = run_validation(FIXTURES_DIR)
    assert r.auc is None or 0.0 <= r.auc <= 1.0
    # Every scenario MTTD is either None or a non-negative float.
    for s in r.attack_scenarios:
        assert s.mttd_seconds is None or s.mttd_seconds >= 0.0
    # Every missed red-team record is attributed exactly once.
    assert len(r.missed_attributions) == r.false_negatives
