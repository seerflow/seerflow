"""Unit tests for ``ExplanationResult`` (S-071, Task 1)."""

from __future__ import annotations

import dataclasses

import pytest

from seerflow.llm.explanation import ExplanationResult


@pytest.mark.unit
def test_result_construction_exposes_all_fields() -> None:
    result = ExplanationResult(
        alert_id="a",
        summary="s",
        anomaly_rationale="r",
        contributing_events=("e",),
        recommended_next_steps=("n",),
        model="llama_cpp",
        generated_at_ns=1,
        latency_ms=0.5,
        cached=False,
        truncated=False,
    )
    assert result.alert_id == "a"
    assert result.summary == "s"
    assert result.anomaly_rationale == "r"
    assert result.contributing_events == ("e",)
    assert result.recommended_next_steps == ("n",)
    assert result.model == "llama_cpp"
    assert result.generated_at_ns == 1
    assert result.latency_ms == 0.5
    assert result.cached is False
    assert result.truncated is False


@pytest.mark.unit
def test_result_is_frozen() -> None:
    result = ExplanationResult(
        alert_id="a",
        summary="s",
        anomaly_rationale="r",
        contributing_events=(),
        recommended_next_steps=(),
        model="llama_cpp",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
        truncated=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.summary = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_result_replace_supports_cached_clone() -> None:
    """``dataclasses.replace`` should clone with a ``cached=True`` override."""
    result = ExplanationResult(
        alert_id="a",
        summary="s",
        anomaly_rationale="r",
        contributing_events=(),
        recommended_next_steps=(),
        model="llama_cpp",
        generated_at_ns=0,
        latency_ms=2.5,
        cached=False,
        truncated=False,
    )
    cached = dataclasses.replace(result, cached=True, latency_ms=0.0)
    assert cached is not result
    assert cached.cached is True
    assert cached.latency_ms == 0.0
    assert cached.summary == "s"
