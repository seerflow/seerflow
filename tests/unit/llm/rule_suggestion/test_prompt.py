"""Unit tests for ``seerflow.llm.rule_suggestion.prompt.build_prompt``.

Covers AC11: deterministic, pure, per-field-capped prompt assembly with
oldest-first sample dropping on overflow.
"""

from __future__ import annotations

import uuid

import pytest

from seerflow.llm.rule_suggestion.prompt import (
    _FIELD_CHAR_CAP,
    build_prompt,
)
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent


def _alert(
    *,
    alert_id: str = "a1",
    alert_type: str = "ml",
    rule_name: str = "hst-anomaly",
    entity_type: str = "ip",
    entity_value: str = "10.0.0.1",
    description: str = "Anomaly detected",
    severity_id: int = 5,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=severity_id,  # type: ignore[arg-type]
        rule_name=rule_name,
        description=description,
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, entity_value)),
        entity_value=entity_value,
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(),
        mitre_tactics=("Discovery",),
        mitre_techniques=("T1046",),
    )


def _event(
    *,
    message: str = "ssh: invalid user from 10.0.0.1",
    source_type: str = "syslog",
    template_id: int = 42,
    ts: int = 1_700_000_000_000_000_000,
) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=ts,
        observed_ns=ts,
        source_type=source_type,
        message=message,
        template_id=template_id,
    )


class TestBuildPrompt:
    def test_deterministic_same_inputs_same_output(self) -> None:
        """AC11: pure function — same inputs, same output."""
        alerts = (_alert(),)
        events = (_event(),)
        p1, t1 = build_prompt("ml:hst-anomaly:ip", alerts, events)
        p2, t2 = build_prompt("ml:hst-anomaly:ip", alerts, events)
        assert p1 == p2
        assert t1 == t2

    def test_pattern_key_in_prompt(self) -> None:
        alerts = (_alert(),)
        events = (_event(),)
        prompt, _ = build_prompt("ml:hst-anomaly:ip", alerts, events)
        assert "ml:hst-anomaly:ip" in prompt

    def test_includes_sigma_one_shot_example(self) -> None:
        """AC11: a one-shot SigmaHQ example anchors the format."""
        alerts = (_alert(),)
        events = (_event(),)
        prompt, _ = build_prompt("ml:hst-anomaly:ip", alerts, events)
        # The example must surface enough SigmaHQ keywords for the LLM to
        # adopt the format. ``logsource`` and ``detection`` are the load
        # bearing structural keys.
        assert "logsource:" in prompt
        assert "detection:" in prompt
        # The instruction block must demand a fenced YAML response so the
        # parser has something to extract.
        assert "yaml" in prompt.lower()

    def test_long_alert_description_is_capped(self) -> None:
        """AC11: per-field cap (512 chars) protects the prompt budget."""
        huge = "x" * 2000
        alerts = (_alert(description=huge),)
        events = (_event(),)
        prompt, _ = build_prompt("ml:hst-anomaly:ip", alerts, events)
        # The capped description should appear with the truncation marker
        # exactly once.
        assert "..." in prompt
        # The full 2000-char description should never be embedded verbatim.
        assert huge not in prompt
        # Bounded — total prompt must not be wildly larger than 8 KB.
        assert len(prompt) < 8_500

    def test_field_char_cap_constant(self) -> None:
        """Per-field cap matches the module-level constant."""
        assert _FIELD_CHAR_CAP == 512

    def test_long_event_message_is_capped(self) -> None:
        """AC11: per-field cap also applies to event ``message`` field."""
        huge = "y" * 2000
        alerts = (_alert(),)
        events = (_event(message=huge),)
        prompt, _ = build_prompt("ml:hst-anomaly:ip", alerts, events)
        assert huge not in prompt

    def test_overflow_drops_oldest_samples(self) -> None:
        """AC11: when budget is tight, oldest samples are dropped first.

        Aggregator contract: samples arrive newest-first (index 0 = newest,
        index -1 = oldest). The builder must drop the tail first.
        """
        # 4 alerts and 4 events, newest-first per the aggregator contract.
        # a-0 / msg-0 is the newest sample; it must survive truncation.
        alerts = tuple(_alert(alert_id=f"a-{i}", entity_value=f"10.0.0.{i}") for i in range(4))
        events = tuple(_event(message=f"msg-{i}", ts=2_000 - i) for i in range(4))
        # Tight cap — assembled prompt must overflow at least once.
        prompt, truncated = build_prompt(
            "ml:hst-anomaly:ip",
            alerts,
            events,
            max_prompt_chars=1500,
        )
        assert truncated is True
        # The newest sample (a-0 + msg-0) must survive when oldest dropped.
        assert "msg-0" in prompt
        # The oldest sample (msg-3) must be the first to disappear.
        assert "msg-3" not in prompt
        assert len(prompt) <= 1500 + _FIELD_CHAR_CAP  # allow last-pass slack

    def test_no_samples_still_returns_valid_prompt(self) -> None:
        """AC11: empty samples produces a structurally valid prompt."""
        prompt, truncated = build_prompt("ml:hst-anomaly:ip", (), ())
        assert truncated is False
        assert "ml:hst-anomaly:ip" in prompt
        assert "yaml" in prompt.lower()

    def test_truncated_flag_false_for_small_input(self) -> None:
        """AC11: ``truncated`` is ``False`` when nothing is dropped."""
        alerts = (_alert(),)
        events = (_event(),)
        _, truncated = build_prompt("ml:hst-anomaly:ip", alerts, events, max_prompt_chars=10_000)
        assert truncated is False

    @pytest.mark.parametrize("description", ["x" * 0, "x" * 512])
    def test_cap_boundary(self, description: str) -> None:
        """AC11: descriptions at the cap boundary are not over-truncated."""
        alerts = (_alert(description=description),)
        events = (_event(),)
        prompt, _ = build_prompt("ml:hst-anomaly:ip", alerts, events)
        if description:
            assert description in prompt
