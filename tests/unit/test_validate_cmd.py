"""Unit tests for seerflow.validate_cmd: derivation, dict shape, CLI."""

from __future__ import annotations

from seerflow.lanl.validator import ValidationResult
from seerflow.validate_cmd import _mttd_seconds, _result_to_dict

_AUC_NOTE = (
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
    )
    base.update(over)
    return ValidationResult(**base)  # type: ignore[arg-type]


def test_mttd_seconds_mean_of_latencies() -> None:
    assert _mttd_seconds({"a": 10.0, "b": 30.0}) == 20.0


def test_mttd_seconds_empty_is_zero() -> None:
    assert _mttd_seconds({}) == 0.0


def test_result_to_dict_shape_and_auc_null() -> None:
    d = _result_to_dict(_vr(), dataset_dir="/data/lanl")
    assert d["auc"] is None
    assert d["auc_note"] == _AUC_NOTE
    assert d["mttd_seconds"] == 20.0
    assert d["precision"] == 0.9231
    assert d["recall"] == 1.0
    assert d["f1"] == 0.96
    assert d["false_positive_rate"] == 0.0769
    assert d["true_positives"] == 12
    assert d["false_positives"] == 1
    assert d["false_negatives"] == 0
    assert d["total_events_processed"] == 203
    assert d["total_alerts"] == 13
    assert d["dataset_dir"] == "/data/lanl"
    assert d["patterns_detected"] == ["brute-force", "c2-beaconing"]


import argparse
import json

import pytest

from seerflow import validate_cmd


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
    assert out["auc"] is None
    assert out["mttd_seconds"] == 10.0
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
    assert "mttd" in out.lower()
