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
