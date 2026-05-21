"""Determinism guard (S-305 / SEE-268 CI remediation).

The LANL full-stack harness must yield byte-identical metrics across
repeated in-process runs *and* across machines of differing speed. The
original implementation rebased events to ``now - 60s`` and let the two
wall-clock-relative aging components in the correlation stack
(``EntityWindowBuffer`` pruning + ``RiskRegister`` exponential decay)
measure event age against an *advancing* ``time.time_ns()``. On a slower
CI runner more real time elapsed during the ~137-event replay, so the
sliding-window cutoff / risk decay shifted relative to the fixed event
timestamps and the alert count drifted (CI: P=2/11=18.18%; local:
P=2/12=16.67%), breaking the README drift guard.

These tests pin the contract: the harness clock is anchored to the event
stream, not wall-clock, so two runs — even with an artificial processing
delay simulating a slow machine — produce identical metrics.
"""

from __future__ import annotations

import time
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"


def _metrics_tuple(r: object) -> tuple[float, ...]:
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


def test_two_inprocess_runs_yield_identical_metrics() -> None:
    """Back-to-back runs must produce byte-identical metrics."""
    from seerflow.lanl.validator import run_validation

    first = run_validation(FIXTURES_DIR)
    second = run_validation(FIXTURES_DIR)

    assert _metrics_tuple(first) == _metrics_tuple(second)


def test_metrics_invariant_under_replay_wallclock_drift(monkeypatch) -> None:
    """A slow machine (wall-clock advancing *during* the replay) must not
    change the harness metrics.

    This reproduces the exact CI failure mode: the two aging components in
    the correlation stack — ``EntityWindowBuffer`` (lazy prune) and
    ``RiskRegister`` (exponential decay) — call ``time.time_ns()`` to
    measure event age. We make every such call jump forward by a fixed
    delta, emulating a runner where minutes of real time elapse while the
    ~137 events stream through the full stack. If the harness did not
    anchor those components to a frozen replay clock, the window cutoff /
    risk decay would shift and the alert count (hence precision) would
    drift, exactly as it did between the agent's machine (P=16.67%) and
    CI (P=18.18%).
    """
    import seerflow.correlation.risk as risk_mod
    import seerflow.correlation.window as window_mod
    from seerflow.lanl.validator import run_validation

    baseline = run_validation(FIXTURES_DIR)

    real_time_ns = time.time_ns
    drift_state = {"calls": 0}
    step_ns = 30 * 1_000_000_000  # +30s of synthetic drift per aging call

    def drifting_time_ns() -> int:
        drift_state["calls"] += 1
        return real_time_ns() + drift_state["calls"] * step_ns

    # Patch the exact symbols the aging components resolve at call time.
    # The harness must neutralise this by freezing the clock these
    # modules see for the duration of the replay.
    monkeypatch.setattr(window_mod.time, "time_ns", drifting_time_ns)
    monkeypatch.setattr(risk_mod.time, "time_ns", drifting_time_ns)

    drifted = run_validation(FIXTURES_DIR)

    assert _metrics_tuple(drifted) == _metrics_tuple(baseline)
