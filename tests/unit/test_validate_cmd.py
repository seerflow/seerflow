"""Unit tests for seerflow.validate_cmd: derivation, dict shape, CLI."""

from __future__ import annotations

import argparse
import json

import pytest

from seerflow import validate_cmd
from seerflow.lanl.attack_metrics import AttackScenarioMetrics, MissedAttribution
from seerflow.lanl.validator import ValidationResult
from seerflow.validate_cmd import _result_to_dict

# S-311 removed the FR-079/S-309 "not computed" placeholder note; this
# constant is kept only to assert the deprecated string is absent.
_OLD_AUC_NOTE = (
    "AUC over a score-threshold sweep is delivered by FR-079 (S-309); "
    "not computed by run_validation."
)


def _vr(**over: object) -> ValidationResult:
    base: dict[str, object] = dict(
        true_positives=12,
        false_positives=1,
        false_negatives=0,
        precision=0.9231,
        recall=1.0,
        f1_score=0.96,
        false_positive_rate=0.0769,
        detection_latency_s={"brute-force": 10.0, "c2-beaconing": 30.0},
        patterns_detected=frozenset({"c2-beaconing", "brute-force"}),
        total_events_processed=203,
        total_alerts=13,
        attack_scenarios=(
            AttackScenarioMetrics(
                name="brute-force-lateral-movement",
                first_event_time_s=110,
                record_count=1,
                detected=True,
                mttd_seconds=40.0,
                missed_record_count=0,
            ),
            AttackScenarioMetrics(
                name="c2-beaconing",
                first_event_time_s=300,
                record_count=2,
                detected=False,
                mttd_seconds=None,
                missed_record_count=2,
            ),
        ),
        pr_points=((0.0, 0.92, 1.0), (1.0, 1.0, 0.0)),
        roc_points=((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
        auc=0.875,
        missed_attributions=(
            MissedAttribution(
                record_repr="300|?|C9999|C8888",
                scenario_name="c2-beaconing",
                silent_family="correlation",
            ),
        ),
    )
    base.update(over)
    return ValidationResult(**base)  # type: ignore[arg-type]


def test_result_to_dict_emits_real_auc_and_no_placeholder() -> None:
    """S-311 / FR-079 AC4: real AUC, per-scenario MTTD, placeholder gone."""
    d = _result_to_dict(_vr(), dataset_dir="/data/lanl")
    assert d["auc"] == 0.875
    assert "auc_note" not in d
    assert _OLD_AUC_NOTE not in str(d)
    scenarios = d["attack_scenarios"]
    assert isinstance(scenarios, list)
    by_name = {s["name"]: s for s in scenarios}
    assert by_name["brute-force-lateral-movement"]["mttd_seconds"] == 40.0
    assert by_name["c2-beaconing"]["mttd_seconds"] is None
    assert d["missed_attributions"][0]["silent_family"] == "correlation"
    assert d["pr_points"] == [[0.0, 0.92, 1.0], [1.0, 1.0, 0.0]]
    assert d["roc_points"] == [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
    assert d["precision"] == 0.9231
    assert d["recall"] == 1.0
    assert d["f1"] == 0.96
    assert d["false_positive_rate"] == 0.0769
    assert d["true_positives"] == 12
    assert d["dataset_dir"] == "/data/lanl"
    assert d["patterns_detected"] == ["brute-force", "c2-beaconing"]


def test_result_to_dict_is_msgspec_encodable_and_deterministic() -> None:
    """AC4: the document round-trips through msgspec and is stable."""
    import msgspec.json

    a = msgspec.json.encode(_result_to_dict(_vr(), dataset_dir="/d"))
    b = msgspec.json.encode(_result_to_dict(_vr(), dataset_dir="/d"))
    assert a == b


def _ns(**kw: object) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def test_validate_dataset_dir_missing_raises(tmp_path: object) -> None:
    missing = tmp_path / "nope"  # type: ignore[operator]
    with pytest.raises(validate_cmd._UsageError):
        validate_cmd._validate_dataset_dir(str(missing))


def test_validate_dataset_dir_is_file_raises(tmp_path: object) -> None:
    f = tmp_path / "auth.csv"  # type: ignore[operator]
    f.write_text("x", encoding="utf-8")
    with pytest.raises(validate_cmd._UsageError):
        validate_cmd._validate_dataset_dir(str(f))


def test_validate_dataset_dir_ok(tmp_path: object) -> None:
    assert validate_cmd._validate_dataset_dir(str(tmp_path)) == tmp_path


def test_run_validate_missing_dir_exit_2_no_harness(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called = False

    def _boom(_p: object) -> object:  # pragma: no cover - must not run
        nonlocal called
        called = True
        raise AssertionError("run_validation must not be called")

    monkeypatch.setattr("seerflow.lanl.validator.run_validation", _boom)
    rc = validate_cmd.run_validate(
        _ns(dataset_dir=str(tmp_path / "x"), json=False)  # type: ignore[operator]
    )
    assert rc == validate_cmd.EXIT_USAGE
    assert called is False
    assert "Error:" in capsys.readouterr().err


def test_run_validate_json_emits_object(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vr = ValidationResult(
        true_positives=12,
        false_positives=1,
        false_negatives=0,
        precision=0.92,
        recall=1.0,
        f1_score=0.96,
        false_positive_rate=0.08,
        detection_latency_s={"r": 10.0},
        patterns_detected=frozenset({"r"}),
        total_events_processed=203,
        total_alerts=13,
    )
    monkeypatch.setattr("seerflow.lanl.validator.run_validation", lambda _p: vr)
    rc = validate_cmd.run_validate(_ns(dataset_dir=str(tmp_path), json=True))
    assert rc == validate_cmd.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    # No alerts/scenarios in this minimal VR -> auc stays None (sentinel),
    # but the attack-metric keys are present and the placeholder is gone.
    assert out["auc"] is None
    assert "auc_note" not in out
    assert out["attack_scenarios"] == []
    assert out["dataset_dir"] == str(tmp_path)


def test_run_validate_table_mode(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vr = ValidationResult(
        true_positives=1,
        false_positives=0,
        false_negatives=0,
        precision=1.0,
        recall=1.0,
        f1_score=1.0,
        false_positive_rate=0.0,
        detection_latency_s={},
        patterns_detected=frozenset(),
        total_events_processed=1,
        total_alerts=1,
    )
    monkeypatch.setattr("seerflow.lanl.validator.run_validation", lambda _p: vr)
    rc = validate_cmd.run_validate(_ns(dataset_dir=str(tmp_path), json=False))
    assert rc == validate_cmd.EXIT_OK
    out = capsys.readouterr().out
    assert "precision" in out.lower()
    assert "auc" in out.lower()
    assert "attack_scenarios" in out.lower()


def test_cli_parses_validate() -> None:
    from seerflow.cli import parse_args

    ns = parse_args(["validate", "/data/lanl", "--json"])
    assert ns.command == "validate"
    assert ns.dataset_dir == "/data/lanl"
    assert ns.json is True


def test_cli_parses_benchmark_defaults() -> None:
    from seerflow.cli import parse_args

    ns = parse_args(["benchmark"])
    assert ns.command == "benchmark"
    assert ns.count == 20000
    assert ns.seed == 42
    assert ns.json is False
    assert ns.scorecard is False


def test_cli_benchmark_count_zero_rejected() -> None:
    from seerflow.cli import parse_args

    with pytest.raises(SystemExit) as exc:
        parse_args(["benchmark", "--count", "0"])
    assert exc.value.code == 2


def test_cli_benchmark_count_negative_rejected() -> None:
    from seerflow.cli import parse_args

    with pytest.raises(SystemExit) as exc:
        parse_args(["benchmark", "--count", "-5"])
    assert exc.value.code == 2


def test_cli_benchmark_scorecard_flags() -> None:
    from seerflow.cli import parse_args

    ns = parse_args(["benchmark", "--scorecard", "--dataset-dir", "/d", "--count", "5"])
    assert ns.scorecard is True
    assert ns.dataset_dir == "/d"
    assert ns.count == 5


def test_cli_validate_help_documents_json(capsys: pytest.CaptureFixture[str]) -> None:
    from seerflow.cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(["validate", "--help"])
    out = capsys.readouterr().out
    assert "--json" in out
    assert "dataset" in out.lower()


def test_cli_benchmark_help_documents_scorecard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from seerflow.cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(["benchmark", "--help"])
    out = capsys.readouterr().out
    assert "--scorecard" in out
    assert "--count" in out


def test_top_level_help_lists_new_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from seerflow.cli import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--help"])
    out = capsys.readouterr().out
    assert "validate" in out
    assert "benchmark" in out
