"""Unit tests for the prompt builder (S-071, Task 2)."""

from __future__ import annotations

import uuid

import pytest

from seerflow.llm.explanation.context import EntityBaselineContext
from seerflow.llm.explanation.prompt import build_prompt
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent


def _alert(rule_name: str = "rule.x", description: str = "Test alert") -> Alert:
    return Alert(
        alert_id="11111111-1111-1111-1111-111111111111",
        alert_type="ml",
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=4,
        rule_name=rule_name,
        description=description,
        entity_uuid="22222222-2222-2222-2222-222222222222",
        entity_value="alice",
        entity_type="user",
        contributing_events=(uuid.UUID("33333333-3333-3333-3333-333333333333"),),
        mitre_tactics=("TA0001",),
        mitre_techniques=("T1078",),
        risk_score=0.87,
        dedup_key="dk",
        dedup_count=1,
    )


def _event(idx: int = 0, message: str = "logged in") -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.UUID(int=idx),
        timestamp_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        observed_ns=1_700_000_000_000_000_000 + idx * 1_000_000_000,
        message=message,
        source_type="auth",
    )


@pytest.mark.unit
def test_build_prompt_includes_all_sections() -> None:
    alert = _alert()
    events = (_event(message="bob logged in from 10.0.0.1"),)
    context = EntityBaselineContext(
        entity_uuid=alert.entity_uuid,
        entity_value=alert.entity_value,
        entity_type=alert.entity_type,
        baseline_summary="usually logs in 09-17 UTC",
    )

    prompt, truncated = build_prompt(alert, events, context)

    assert "ALERT:" in prompt
    assert "CONTRIBUTING EVENTS:" in prompt
    assert "ENTITY CONTEXT:" in prompt
    assert "INSTRUCTION:" in prompt
    assert "SUMMARY:" in prompt  # the instruction asks for these tags
    assert "RATIONALE:" in prompt
    assert "EVENTS:" in prompt
    assert "NEXT STEPS:" in prompt
    assert alert.rule_name in prompt
    assert "bob logged in from 10.0.0.1" in prompt
    assert "usually logs in 09-17 UTC" in prompt
    assert truncated is False


@pytest.mark.unit
def test_build_prompt_includes_alert_metadata() -> None:
    alert = _alert()
    prompt, _ = build_prompt(alert, (), None)
    assert alert.alert_id in prompt
    assert alert.entity_value in prompt
    assert alert.alert_type in prompt
    assert "TA0001" in prompt
    assert "T1078" in prompt


@pytest.mark.unit
def test_build_prompt_truncates_when_events_exceed_budget() -> None:
    alert = _alert()
    # Make each event message ~150 chars so 50 events ≈ 7500 chars of payload.
    long_msg = "x" * 150
    events = tuple(_event(idx=i, message=long_msg) for i in range(50))
    prompt, truncated = build_prompt(alert, events, None, max_prompt_chars=2000)
    assert truncated is True
    assert len(prompt) <= 2000


@pytest.mark.unit
def test_build_prompt_truncates_individual_long_fields() -> None:
    very_long = "z" * 1024
    alert = _alert(description=very_long)
    prompt, _ = build_prompt(alert, (), None)
    # Per-field cap is 512 chars; suffix marker present.
    assert very_long not in prompt
    assert "..." in prompt or "…" in prompt


@pytest.mark.unit
def test_build_prompt_handles_missing_entity_context() -> None:
    prompt, _ = build_prompt(_alert(), (), None)
    assert "(no baseline)" in prompt


@pytest.mark.unit
def test_build_prompt_handles_empty_events_tuple() -> None:
    prompt, _ = build_prompt(_alert(), (), None)
    assert "(none recorded)" in prompt


@pytest.mark.unit
def test_build_prompt_handles_context_with_no_baseline_summary() -> None:
    alert = _alert()
    context = EntityBaselineContext(
        entity_uuid=alert.entity_uuid,
        entity_value=alert.entity_value,
        entity_type=alert.entity_type,
        baseline_summary=None,
    )
    prompt, _ = build_prompt(alert, (), context)
    assert "(no baseline)" in prompt
    assert alert.entity_value in prompt


@pytest.mark.unit
def test_build_prompt_keeps_newest_events_when_truncating() -> None:
    """When truncating, newer events should be kept."""
    alert = _alert()
    long_msg = "x" * 200
    # Events sorted oldest-first by timestamp; dropping should remove oldest.
    events = tuple(_event(idx=i, message=f"E{i}-{long_msg}") for i in range(20))
    prompt, truncated = build_prompt(alert, events, None, max_prompt_chars=2000)
    assert truncated is True
    # Newest event (idx=19) must remain; oldest (idx=0) must be dropped.
    assert "E19-" in prompt
    assert "E0-" not in prompt
