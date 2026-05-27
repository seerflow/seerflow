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

import msgspec.json

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "lanl"

# Number of repeats for the loop guards. The CI flake (S-334) surfaced on
# roughly 1-in-2 runs of the attack-metric blob; 20 repeats gives a high
# probability of catching any residual nondeterminism without ballooning the
# suite runtime.
_LOOP_N = 20


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


def _attack_blob(r: object) -> bytes:
    """msgspec-encoded view of the S-311 attack-level fields.

    This is the surface that actually flaked on CI (S-334): the
    ``c2-beaconing`` scenario MTTD and the PR/ROC sweep shifted between two
    runs when a window/risk aging boundary moved under wall-clock drift. The
    headline tuple stayed stable, so a metrics-tuple-only guard missed it.
    """
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


def test_metrics_and_attack_blob_invariant_over_n_runs() -> None:
    """S-334 root-cause guard: the headline tuple *and* the S-311 attack
    blob must be byte-identical across ``_LOOP_N`` repeated in-process runs.

    The pre-S-334 freeze was a module-attribute monkeypatch restored on
    ``with``-block exit; the headline tuple stayed stable but the attack
    blob (MTTD / PR / ROC) flaked on CI when an aging boundary moved under
    real wall-clock drift. With the aging clock dependency-injected and
    anchored to ``REPLAY_EPOCH_NS`` for the whole component lifetime, both
    surfaces are now a pure function of the deterministic event stream.
    """
    from seerflow.lanl.validator import run_validation

    baseline = run_validation(FIXTURES_DIR)
    base_metrics = _metrics_tuple(baseline)
    base_blob = _attack_blob(baseline)

    for _ in range(_LOOP_N):
        r = run_validation(FIXTURES_DIR)
        assert _metrics_tuple(r) == base_metrics
        assert _attack_blob(r) == base_blob


def test_attack_blob_invariant_under_arbitrary_wallclock_drift(monkeypatch) -> None:
    """The injected replay clock must shield the attack blob from *any* real
    wall-clock value — including one months ahead of the replay epoch, as on
    a real CI runner (replay epoch is 2026-01-01; CI clock is later).

    A single leaked wall-clock read in the window/risk aging path would, on
    such a clock, prune the entire rebased window and shift the correlation
    alert that covers the ``c2-beaconing`` scenario — exactly the CI flake.
    Because the clock is now dependency-injected into the aging components
    (not a restored module-attribute patch), the blob is invariant.
    """
    import seerflow.correlation.risk as risk_mod
    import seerflow.correlation.window as window_mod
    from seerflow.lanl.validator import run_validation

    baseline_blob = _attack_blob(run_validation(FIXTURES_DIR))

    # Far-future, monotonically advancing wall-clock (emulates a slow CI
    # runner whose real clock is well past the 2026-01-01 replay epoch).
    real_time_ns = time.time_ns
    drift_state = {"calls": 0}
    far_future = 1_800_000_000_000_000_000  # ~2027-01-15, far past the epoch

    def far_future_time_ns() -> int:
        drift_state["calls"] += 1
        return far_future + drift_state["calls"] * 30 * 1_000_000_000

    monkeypatch.setattr(window_mod.time, "time_ns", far_future_time_ns)
    monkeypatch.setattr(risk_mod.time, "time_ns", far_future_time_ns)
    # Sanity: the patched module clock really is far past the replay epoch,
    # so any leak would be observable.
    assert window_mod.time.time_ns() > 1_770_000_000_000_000_000
    assert real_time_ns() < far_future

    drifted_blob = _attack_blob(run_validation(FIXTURES_DIR))

    assert drifted_blob == baseline_blob
