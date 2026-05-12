"""Unit tests for ``HuntResult`` (S-072, Task 5)."""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from seerflow.llm.hunt.result import HuntResult
from seerflow.models.event import SeerflowEvent


def _event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="ssh login",
        source_type="auth",
    )


@pytest.mark.unit
def test_hunt_result_construction() -> None:
    r = HuntResult(
        query="ssh from external",
        filters={"text_query": "ssh"},
        events=(_event(),),
        total=1,
        model="fake_llm",
        generated_at_ns=1_700_000_000_000_000_000,
        latency_ms=1.5,
        cached=False,
        truncated=False,
    )
    assert r.query == "ssh from external"
    assert r.total == 1
    assert r.cached is False


@pytest.mark.unit
def test_hunt_result_is_frozen() -> None:
    r = HuntResult(
        query="x",
        filters={},
        events=(),
        total=0,
        model="m",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
        truncated=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.cached = True  # type: ignore[misc]


@pytest.mark.unit
def test_hunt_result_replace_returns_new_instance() -> None:
    r = HuntResult(
        query="x",
        filters={},
        events=(),
        total=0,
        model="m",
        generated_at_ns=0,
        latency_ms=0.0,
        cached=False,
        truncated=False,
    )
    r2 = dataclasses.replace(r, cached=True, latency_ms=0.0)
    assert r2.cached is True
    assert r2 is not r
    # Original unchanged.
    assert r.cached is False


@pytest.mark.unit
def test_hunt_result_requires_kw_args() -> None:
    with pytest.raises(TypeError):
        HuntResult("x", {}, (), 0, "m", 0, 0.0, False, False)  # type: ignore[misc,call-arg]
