"""Unit tests for ``AlertExplanationResponse`` (S-071, Task 7)."""

from __future__ import annotations

import pytest

from seerflow.api.schemas import AlertExplanationResponse
from seerflow.llm.explanation.result import ExplanationResult


def _result(**overrides: object) -> ExplanationResult:
    defaults: dict[str, object] = {
        "alert_id": "a",
        "summary": "s",
        "anomaly_rationale": "r",
        "contributing_events": ("e1", "e2"),
        "recommended_next_steps": ("n1",),
        "model": "llama_cpp",
        "generated_at_ns": 1_700_000_000_000_000_000,
        "latency_ms": 2.5,
        "cached": False,
        "truncated": True,
    }
    defaults.update(overrides)
    return ExplanationResult(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
def test_from_result_mirrors_all_fields() -> None:
    response = AlertExplanationResponse.from_result(_result())
    assert response.alert_id == "a"
    assert response.summary == "s"
    assert response.anomaly_rationale == "r"
    assert response.contributing_events == ["e1", "e2"]
    assert response.recommended_next_steps == ["n1"]
    assert response.model == "llama_cpp"
    assert response.generated_at_ns == 1_700_000_000_000_000_000
    assert response.latency_ms == 2.5
    assert response.cached is False
    assert response.truncated is True


@pytest.mark.unit
def test_model_dump_round_trip() -> None:
    response = AlertExplanationResponse.from_result(_result(cached=True))
    dumped = response.model_dump()
    assert dumped["cached"] is True
    assert dumped["contributing_events"] == ["e1", "e2"]
    rebuilt = AlertExplanationResponse(**dumped)
    assert rebuilt == response


@pytest.mark.unit
def test_generated_at_ns_serialises_as_string_in_json_mode() -> None:
    response = AlertExplanationResponse.from_result(_result())
    json_dump = response.model_dump(mode="json")
    assert isinstance(json_dump["generated_at_ns"], str)
    assert json_dump["generated_at_ns"] == "1700000000000000000"


@pytest.mark.unit
def test_python_mode_keeps_native_int() -> None:
    response = AlertExplanationResponse.from_result(_result())
    python_dump = response.model_dump(mode="python")
    assert isinstance(python_dump["generated_at_ns"], int)
