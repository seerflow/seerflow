"""Unit tests for the S-310 benchmark scorecard (pure cores)."""

from __future__ import annotations

import pytest

from seerflow.benchmark.scorecard import (
    GateResult,
    Scorecard,
    append_history,
    build_scorecard,
    evaluate_regression,
    resolve_git_sha,
    scorecard_to_dict,
)
from seerflow.lanl.validator import FamilyMetrics, ValidationResult
from seerflow.launch.benchmark import BenchmarkResult


def _vr(**over: object) -> ValidationResult:
    base = dict(
        true_positives=2,
        false_positives=10,
        false_negatives=4,
        precision=0.16666666666666666,
        recall=0.3333333333333333,
        f1_score=0.2222222222222222,
        false_positive_rate=0.8333333333333334,
        detection_latency_s={},
        patterns_detected=frozenset({"r1"}),
        total_events_processed=137,
        total_alerts=12,
        per_family={
            "ml": FamilyMetrics(
                true_positives=1,
                false_positives=2,
                false_negatives=0,
                precision=0.3333333333333333,
                recall=1.0,
                f1_score=0.5,
                total_alerts=3,
            )
        },
        scope_label="full detection stack on synthetic LANL subset",
    )
    base.update(over)
    return ValidationResult(**base)  # type: ignore[arg-type]


def _br(**over: object) -> BenchmarkResult:
    base = dict(
        event_count=2000,
        elapsed_s=0.5,
        throughput_eps=4000.0,
        latency_p50_ms=0.12,
        latency_p95_ms=0.34,
        latency_mean_ms=0.2,
        peak_rss_mb=187.5,
        stored_events=2000,
        alerts=3,
    )
    base.update(over)
    return BenchmarkResult(**base)  # type: ignore[arg-type]


def test_build_scorecard_maps_all_fields() -> None:
    sc = build_scorecard(
        _vr(),
        _br(),
        git_sha="abc123",
        timestamp="2026-05-18T00:00:00+00:00",
    )
    assert isinstance(sc, Scorecard)
    assert sc.git_sha == "abc123"
    assert sc.timestamp == "2026-05-18T00:00:00+00:00"
    assert sc.precision == pytest.approx(0.16666666666666666)
    assert sc.recall == pytest.approx(0.3333333333333333)
    assert sc.f1_score == pytest.approx(0.2222222222222222)
    assert sc.throughput_eps == pytest.approx(4000.0)
    assert sc.peak_rss_mb == pytest.approx(187.5)
    assert sc.scope_label == "full detection stack on synthetic LANL subset"
    assert sc.benchmark_event_count == 2000


def test_scorecard_to_dict_is_deterministic() -> None:
    a = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="s", timestamp="t"))
    b = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="s", timestamp="t"))
    import json

    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["schema_version"] == 1
    assert a["accuracy"]["recall"] == pytest.approx(0.3333333333333333)
    assert a["performance"]["throughput_eps"] == pytest.approx(4000.0)
    assert "ml" in a["accuracy"]["per_family"]
    assert a["accuracy"]["per_family"]["ml"]["precision"] == pytest.approx(0.3333333333333333)


def test_peak_rss_none_serializes_null() -> None:
    sc = build_scorecard(_vr(), _br(peak_rss_mb=None), git_sha="s", timestamp="t")
    d = scorecard_to_dict(sc)
    assert d["performance"]["peak_rss_mb"] is None


def test_append_history_empty_when_no_file(tmp_path) -> None:
    cur = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="g1", timestamp="t1"))
    merged = append_history(cur, tmp_path / "missing.json")
    assert merged["history"] == []
    assert merged["git_sha"] == "g1"


def test_append_history_preserves_prior_entries(tmp_path) -> None:
    import json

    p = tmp_path / "benchmark-results.json"
    first = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="g1", timestamp="t1"))
    p.write_text(json.dumps(append_history(first, p)), encoding="utf-8")
    second = scorecard_to_dict(
        build_scorecard(_vr(recall=0.5), _br(), git_sha="g2", timestamp="t2")
    )
    merged = append_history(second, p)
    assert merged["git_sha"] == "g2"
    assert len(merged["history"]) == 1
    assert merged["history"][0]["git_sha"] == "g1"
    assert merged["history"][0]["accuracy_summary"]["recall"] == pytest.approx(0.3333333333333333)


def test_append_history_handles_corrupt_file(tmp_path) -> None:
    p = tmp_path / "benchmark-results.json"
    p.write_text("not json", encoding="utf-8")
    cur = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="g", timestamp="t"))
    merged = append_history(cur, p)
    assert merged["history"] == []


def test_append_history_prior_history_not_a_list(tmp_path) -> None:
    import json

    p = tmp_path / "benchmark-results.json"
    # Malformed prior file: a dict but `history` is not a list, and it
    # carries no accuracy block -> fresh empty history, no crash.
    p.write_text(json.dumps({"history": "nope"}), encoding="utf-8")
    cur = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="g", timestamp="t"))
    merged = append_history(cur, p)
    assert merged["history"] == []


def test_append_history_prior_without_accuracy_block(tmp_path) -> None:
    import json

    p = tmp_path / "benchmark-results.json"
    # Prior dict has history entries but no top-level git_sha/accuracy ->
    # the prior entries carry forward but no summary is appended.
    p.write_text(json.dumps({"history": [{"git_sha": "old"}]}), encoding="utf-8")
    cur = scorecard_to_dict(build_scorecard(_vr(), _br(), git_sha="g", timestamp="t"))
    merged = append_history(cur, p)
    assert merged["history"] == [{"git_sha": "old"}]


def test_gate_fails_on_precision_and_f1_regression() -> None:
    base = scorecard_to_dict(
        build_scorecard(_vr(precision=1.0, f1_score=1.0), _br(), git_sha="g", timestamp="t")
    )
    cand = scorecard_to_dict(
        build_scorecard(_vr(precision=0.5, f1_score=0.5), _br(), git_sha="g", timestamp="t")
    )
    res = evaluate_regression(cand, base)
    assert res.passed is False
    assert any("precision" in f for f in res.failures)
    assert any("f1_score" in f for f in res.failures)


def test_section_rejects_non_object() -> None:
    from seerflow.benchmark.scorecard import _section

    with pytest.raises(TypeError, match="not an object"):
        _section({"accuracy": "oops"}, "accuracy")


def test_resolve_git_sha_empty_stdout_returns_unknown(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    import seerflow.benchmark.scorecard as mod

    class _CP:
        stdout = "   \n"

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _CP())
    assert resolve_git_sha() == "unknown"


def _card(recall: float = 0.3333333333333333, thr: float = 4000.0) -> dict:
    return scorecard_to_dict(
        build_scorecard(
            _vr(recall=recall),
            _br(throughput_eps=thr),
            git_sha="g",
            timestamp="t",
        )
    )


def test_gate_passes_on_identical() -> None:
    base = _card()
    res = evaluate_regression(_card(), base)
    assert isinstance(res, GateResult)
    assert res.passed is True
    assert res.failures == []


def test_gate_passes_at_5pct_boundary() -> None:
    base = _card(recall=1.0)
    res = evaluate_regression(_card(recall=0.95), base)
    assert res.passed is True


def test_gate_fails_on_6pct_recall_drop() -> None:
    base = _card(recall=1.0)
    res = evaluate_regression(_card(recall=0.94), base)
    assert res.passed is False
    assert any("recall" in f for f in res.failures)


def test_gate_fails_on_throughput_regression() -> None:
    base = _card(thr=4000.0)
    res = evaluate_regression(_card(thr=3000.0), base)
    assert res.passed is False
    assert any("throughput_eps" in f for f in res.failures)


def test_gate_ignores_zero_baseline_metric() -> None:
    base = _card(recall=0.0)
    res = evaluate_regression(_card(recall=0.0), base)
    assert res.passed is True


def test_resolve_git_sha_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    assert resolve_git_sha() == "deadbeef"


def test_resolve_git_sha_subprocess_fallback(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    import seerflow.benchmark.scorecard as mod

    class _CP:
        stdout = "cafef00d\n"

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _CP())
    assert resolve_git_sha() == "cafef00d"


def test_resolve_git_sha_git_not_on_path(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    import seerflow.benchmark.scorecard as mod

    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert resolve_git_sha() == "unknown"


def test_resolve_git_sha_failure_returns_unknown(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    import seerflow.benchmark.scorecard as mod

    def _boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(mod.subprocess, "run", _boom)
    assert resolve_git_sha() == "unknown"


def test_main_check_passes_against_self(tmp_path, monkeypatch) -> None:
    """End-to-end: write artifact, gate against a baseline == itself."""
    import json

    import seerflow.benchmark.scorecard as mod

    sc = build_scorecard(_vr(), _br(), git_sha="g", timestamp="t")
    card = scorecard_to_dict(sc)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(card), encoding="utf-8")
    out = tmp_path / "benchmark-results.json"

    monkeypatch.setattr(mod, "_run_validation_for_scorecard", lambda: _vr())
    monkeypatch.setattr(mod, "_run_benchmark_for_scorecard", lambda: _br())
    monkeypatch.setattr(mod, "resolve_git_sha", lambda: "g")
    monkeypatch.setattr(mod, "_now_iso", lambda: "t")

    rc = mod.main(["--out", str(out), "--check", str(baseline)])
    assert rc == 0
    assert out.exists()
    assert json.loads(out.read_text())["accuracy"]["recall"] == pytest.approx(0.3333333333333333)


def test_main_check_fails_on_regression(tmp_path, monkeypatch) -> None:
    import json

    import seerflow.benchmark.scorecard as mod

    strong = scorecard_to_dict(build_scorecard(_vr(recall=1.0), _br(), git_sha="g", timestamp="t"))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(strong), encoding="utf-8")
    out = tmp_path / "benchmark-results.json"

    monkeypatch.setattr(mod, "_run_validation_for_scorecard", lambda: _vr(recall=0.5))
    monkeypatch.setattr(mod, "_run_benchmark_for_scorecard", lambda: _br())
    monkeypatch.setattr(mod, "resolve_git_sha", lambda: "g")
    monkeypatch.setattr(mod, "_now_iso", lambda: "t")

    rc = mod.main(["--out", str(out), "--check", str(baseline)])
    assert rc == 1


def test_main_check_missing_baseline_fails_closed(tmp_path, monkeypatch) -> None:
    import seerflow.benchmark.scorecard as mod

    monkeypatch.setattr(mod, "_run_validation_for_scorecard", lambda: _vr())
    monkeypatch.setattr(mod, "_run_benchmark_for_scorecard", lambda: _br())
    monkeypatch.setattr(mod, "resolve_git_sha", lambda: "g")
    monkeypatch.setattr(mod, "_now_iso", lambda: "t")

    rc = mod.main(
        [
            "--out",
            str(tmp_path / "o.json"),
            "--check",
            str(tmp_path / "nope.json"),
        ]
    )
    assert rc == 1
