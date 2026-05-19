"""Integration: real-harness scorecard + NFR-016 gate proof + CI YAML.

Covers AC1 (artifact populated, all fields), AC2 (accuracy sourced verbatim
from ``run_validation``), AC4 (>=6 % recall drop FAILS, 0 % PASSES), and AC3
(``ci.yml`` is valid YAML and the new ``scorecard-gate`` job is additive and
self-contained).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from seerflow.benchmark.scorecard import (
    append_history,
    build_scorecard,
    evaluate_regression,
    scorecard_to_dict,
)
from seerflow.lanl.validator import run_validation
from seerflow.launch.benchmark import run_benchmark

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "lanl"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
BASELINE = REPO / "tests" / "fixtures" / "scorecard_baseline.json"


@pytest.fixture(scope="module")
def real_card() -> dict:
    """Build a scorecard from the real harness + a small real benchmark."""
    validation = run_validation(FIXTURES)
    benchmark = run_benchmark(200)
    sc = build_scorecard(
        validation, benchmark, git_sha="itest", timestamp="itest"
    )
    return scorecard_to_dict(sc)


def test_artifact_is_populated_with_all_ac1_fields(real_card, tmp_path) -> None:
    merged = append_history(real_card, tmp_path / "x.json")
    acc = merged["accuracy"]
    perf = merged["performance"]
    for key in (
        "precision",
        "recall",
        "f1_score",
        "false_positive_rate",
        "true_positives",
        "false_positives",
        "false_negatives",
        "total_events_processed",
        "total_alerts",
        "scope_label",
        "per_family",
    ):
        assert key in acc, f"missing accuracy.{key}"
    for key in (
        "throughput_eps",
        "latency_p50_ms",
        "latency_p95_ms",
        "peak_rss_mb",
        "benchmark_event_count",
    ):
        assert key in perf, f"missing performance.{key}"
    assert merged["git_sha"] == "itest"
    assert merged["timestamp"] == "itest"
    assert merged["history"] == []
    assert "synthetic lanl subset" in acc["scope_label"].lower()


def test_accuracy_matches_run_validation(real_card) -> None:
    vr = run_validation(FIXTURES)
    assert real_card["accuracy"]["recall"] == pytest.approx(vr.recall)
    assert real_card["accuracy"]["precision"] == pytest.approx(vr.precision)
    assert real_card["accuracy"]["f1_score"] == pytest.approx(vr.f1_score)


def test_zero_drop_passes_gate(real_card) -> None:
    res = evaluate_regression(real_card, copy.deepcopy(real_card))
    assert res.passed is True
    assert res.failures == []


def test_six_percent_recall_drop_fails_gate(real_card) -> None:
    baseline = copy.deepcopy(real_card)
    # Strong baseline so a 6 % relative drop is representable.
    baseline["accuracy"]["recall"] = 1.0
    candidate = copy.deepcopy(real_card)
    candidate["accuracy"]["recall"] = 0.94
    res = evaluate_regression(candidate, baseline)
    assert res.passed is False
    assert any("recall" in f for f in res.failures)


def test_committed_baseline_passes_against_itself() -> None:
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    res = evaluate_regression(base, base)
    assert res.passed is True


def test_ci_yaml_is_valid_and_additive() -> None:
    import yaml

    doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    # Existing jobs survive untouched.
    assert "check" in jobs
    assert "frontend-e2e" in jobs
    # New additive job present, synthetic-subset, self-contained.
    assert "scorecard-gate" in jobs
    sg = jobs["scorecard-gate"]
    assert "needs" not in sg  # independent of `check`; cannot block siblings
    flat = json.dumps(sg)
    assert "seerflow.benchmark.scorecard" in flat
    assert "scorecard_baseline.json" in flat
