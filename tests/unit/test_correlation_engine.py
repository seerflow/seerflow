"""Tests for CorrelationEngine — init, matching, evaluation, alert generation.

Covers Tasks 1-4 of S-041: CorrelationEngine init, condition matching,
rule evaluation, and alert generation.
"""

from __future__ import annotations

import re
import time
import uuid

from seerflow.correlation.window import EntityWindowBuffer
from seerflow.models.alert import Alert, CorrelationRule, SourceCondition
from seerflow.models.event import SeerflowEvent, SeverityLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WINDOW_NS = 60_000_000_000  # 60 seconds


def _make_event(
    *,
    message: str = "test event",
    source_type: str = "syslog",
    entity_refs: tuple[str, ...] = (),
    related_ips: tuple[str, ...] = (),
    related_users: tuple[str, ...] = (),
    related_hosts: tuple[str, ...] = (),
    template_str: str = "",
    timestamp_ns: int | None = None,
    event_id: uuid.UUID | None = None,
) -> SeerflowEvent:
    now_ns = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=event_id if event_id is not None else uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=SeverityLevel.INFORMATIONAL,
        message=message,
        source_type=source_type,
        entity_refs=entity_refs,
        related_ips=related_ips,
        related_users=related_users,
        related_hosts=related_hosts,
        template_str=template_str,
    )


def _make_rule(
    *,
    name: str = "test_rule",
    entity_type: str = "ip",
    window_seconds: int = 60,
    sources: tuple[SourceCondition, ...] | None = None,
    min_sources: int = 2,
    alert_severity: SeverityLevel = SeverityLevel.ERROR,
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
    description: str = "Test correlation rule",
) -> CorrelationRule:
    if sources is None:
        sources = (
            SourceCondition(
                source_type="syslog",
                conditions={"message": "Failed password.*"},
                min_count=1,
            ),
            SourceCondition(
                source_type="syslog",
                conditions={"message": "Accepted.*"},
                min_count=1,
            ),
        )
    return CorrelationRule(
        name=name,
        entity_type=entity_type,
        window_seconds=window_seconds,
        sources=sources,
        min_sources=min_sources,
        alert_severity=alert_severity,
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
        description=description,
    )


def _make_window() -> EntityWindowBuffer:
    return EntityWindowBuffer(window_ns=_WINDOW_NS, max_events=1000)


# ---------------------------------------------------------------------------
# Task 1: Init tests
# ---------------------------------------------------------------------------


class TestEngineInit:
    def test_engine_init_with_rules(self) -> None:
        """Engine accepts rules and window, stores them."""
        from seerflow.correlation.engine import CorrelationEngine

        window = _make_window()
        rules = [_make_rule()]
        engine = CorrelationEngine(rules=rules, window=window)
        assert engine._rules == rules
        assert engine._window is window

    def test_engine_with_no_rules_returns_empty(self) -> None:
        """evaluate() with no rules always returns []."""
        from seerflow.correlation.engine import CorrelationEngine

        window = _make_window()
        engine = CorrelationEngine(rules=[], window=window)
        event = _make_event(entity_refs=("uuid-a",), related_ips=("10.0.0.1",))
        alerts = engine.evaluate(event, entity_refs=("uuid-a",))
        assert alerts == []

    def test_engine_compiles_regex_patterns_at_init(self) -> None:
        """Patterns are pre-compiled at init, not compiled per-event."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": r"Failed\s+password.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        compiled = engine._compiled
        assert rule.name in compiled
        assert len(compiled[rule.name]) == 1
        pattern = compiled[rule.name][0]["message"]
        assert isinstance(pattern, re.Pattern)
        assert pattern.pattern == r"Failed\s+password.*"


# ---------------------------------------------------------------------------
# Task 2: Condition matching tests
# ---------------------------------------------------------------------------


class TestConditionMatching:
    def test_match_event_all_conditions_met(self) -> None:
        """Event matching all regex conditions returns True."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={
                        "message": "Failed password.*",
                        "source_type": "syslog",
                    },
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(
            message="Failed password for root from 10.0.0.1",
            source_type="syslog",
        )
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is True

    def test_match_event_partial_conditions_returns_false(self) -> None:
        """Event matching only some conditions returns False."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={
                        "message": "Failed password.*",
                        "source_type": "otlp",  # won't match "syslog"
                    },
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(
            message="Failed password for root",
            source_type="syslog",
        )
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is False

    def test_match_event_regex_pattern(self) -> None:
        """Regex patterns work (not just exact match)."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": r"error\s+\d{3}"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(message="some error 404 occurred")
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is True

    def test_match_event_tuple_field_contains(self) -> None:
        """For tuple fields (related_ips), check if any element matches."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"related_ips": r"10\.0\.0\.\d+"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(related_ips=("192.168.1.1", "10.0.0.5"))
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is True

    def test_match_event_tuple_field_no_match(self) -> None:
        """Tuple field where no element matches returns False."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"related_ips": r"10\.0\.0\.\d+"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(related_ips=("192.168.1.1", "172.16.0.1"))
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is False

    def test_match_event_no_conditions_matches_all(self) -> None:
        """Empty conditions dict matches any event."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event(message="anything at all")
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is True

    def test_match_event_missing_field_returns_false(self) -> None:
        """Condition on a field that is None returns False."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"trace_id": "abc.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)
        event = _make_event()  # trace_id defaults to None
        assert engine._match_event(event, source_idx=0, rule_name=rule.name) is False


# ---------------------------------------------------------------------------
# Task 3: Rule evaluation tests
# ---------------------------------------------------------------------------


class TestRuleEvaluation:
    def test_evaluate_single_rule_two_sources_match(self) -> None:
        """Both source conditions satisfied -> returns alert."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-entity-a"
        rule = _make_rule(
            name="ssh_brute_force",
            entity_type="ip",
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Failed password.*"},
                    min_count=1,
                ),
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Accepted.*"},
                    min_count=1,
                ),
            ),
            min_sources=2,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        # Add events to the window buffer
        fail_event = _make_event(
            message="Failed password for admin",
            source_type="syslog",
            timestamp_ns=now - 1_000_000,
            related_ips=("10.0.0.1",),
        )
        accept_event = _make_event(
            message="Accepted password for admin",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, fail_event)
        window.add_event(entity_uuid, accept_event)

        # Trigger evaluation with the accept event
        alerts = engine.evaluate(accept_event, entity_refs=(entity_uuid,))
        assert len(alerts) == 1
        assert alerts[0].rule_name == "ssh_brute_force"

    def test_evaluate_min_count_not_met(self) -> None:
        """Source has events but below min_count -> no alert."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-entity-b"
        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Failed password.*"},
                    min_count=5,  # requires 5 matching events
                ),
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Accepted.*"},
                    min_count=1,
                ),
            ),
            min_sources=2,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        # Only add 2 failed password events (min_count=5)
        for i in range(2):
            window.add_event(
                entity_uuid,
                _make_event(
                    message="Failed password for admin",
                    source_type="syslog",
                    timestamp_ns=now - (3 - i) * 1_000_000,
                    related_ips=("10.0.0.1",),
                ),
            )
        accept_event = _make_event(
            message="Accepted password for admin",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, accept_event)

        alerts = engine.evaluate(accept_event, entity_refs=(entity_uuid,))
        assert alerts == []

    def test_evaluate_min_sources_not_met(self) -> None:
        """Only 1 of 2 required sources present -> no alert."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-entity-c"
        rule = _make_rule(
            name="multi_source_rule",
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Failed password.*"},
                    min_count=1,
                ),
                SourceCondition(
                    source_type="otlp",
                    conditions={"message": "Suspicious.*"},
                    min_count=1,
                ),
            ),
            min_sources=2,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        # Only add syslog events, no otlp events
        fail_event = _make_event(
            message="Failed password for admin",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, fail_event)

        alerts = engine.evaluate(fail_event, entity_refs=(entity_uuid,))
        assert alerts == []

    def test_evaluate_entity_type_mismatch_skipped(self) -> None:
        """Rule requires 'user' but entity is 'ip' -> skipped."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-entity-d"
        rule = _make_rule(
            entity_type="user",  # Rule expects user entities
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": ".*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        # Event has related_ips but NOT related_users, so entity_type = "ip"
        event = _make_event(
            message="some event",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, event)

        alerts = engine.evaluate(event, entity_refs=(entity_uuid,))
        assert alerts == []

    def test_evaluate_multiple_rules_multiple_alerts(self) -> None:
        """Multiple rules can fire for the same entity."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-entity-e"
        rule_a = _make_rule(
            name="rule_a",
            entity_type="ip",
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Failed.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        rule_b = _make_rule(
            name="rule_b",
            entity_type="ip",
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Failed.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule_a, rule_b], window=window)

        event = _make_event(
            message="Failed authentication attempt",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, event)

        alerts = engine.evaluate(event, entity_refs=(entity_uuid,))
        assert len(alerts) == 2
        rule_names = {a.rule_name for a in alerts}
        assert rule_names == {"rule_a", "rule_b"}

    def test_evaluate_no_entities_returns_empty(self) -> None:
        """Event with no entity_refs -> empty alerts."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": ".*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        event = _make_event(message="some event", source_type="syslog")
        alerts = engine.evaluate(event, entity_refs=())
        assert alerts == []


# ---------------------------------------------------------------------------
# Task 4: Alert generation tests
# ---------------------------------------------------------------------------


class TestAlertGeneration:
    def _fire_engine(
        self,
        *,
        mitre_tactics: tuple[str, ...] = (),
        mitre_techniques: tuple[str, ...] = (),
    ) -> list[Alert]:
        """Helper: sets up an engine+window that fires a single rule, returns alerts."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-alert-entity"
        rule = _make_rule(
            name="alert_gen_rule",
            entity_type="ip",
            alert_severity=SeverityLevel.CRITICAL,
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Suspicious.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
            mitre_tactics=mitre_tactics,
            mitre_techniques=mitre_techniques,
            description="Test alert gen rule",
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        event = _make_event(
            message="Suspicious activity detected",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, event)
        return engine.evaluate(event, entity_refs=(entity_uuid,))

    def test_alert_has_correlation_type(self) -> None:
        """Generated alert has alert_type='correlation'."""
        alerts = self._fire_engine()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "correlation"

    def test_alert_has_mitre_tags_from_rule(self) -> None:
        """ATT&CK tactics/techniques propagated from rule."""
        alerts = self._fire_engine(
            mitre_tactics=("credential-access",),
            mitre_techniques=("T1110.001",),
        )
        assert len(alerts) == 1
        assert alerts[0].mitre_tactics == ("credential-access",)
        assert alerts[0].mitre_techniques == ("T1110.001",)

    def test_alert_has_contributing_events(self) -> None:
        """Alert includes event IDs from matching window events."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-contrib-entity"
        eid1 = uuid.uuid4()
        eid2 = uuid.uuid4()

        rule = _make_rule(
            name="contrib_rule",
            entity_type="ip",
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "Suspicious.*"},
                    min_count=2,
                ),
            ),
            min_sources=1,
        )
        window = _make_window()
        engine = CorrelationEngine(rules=[rule], window=window)

        event1 = _make_event(
            message="Suspicious login attempt",
            source_type="syslog",
            timestamp_ns=now - 1_000_000,
            event_id=eid1,
            related_ips=("10.0.0.1",),
        )
        event2 = _make_event(
            message="Suspicious file access",
            source_type="syslog",
            timestamp_ns=now,
            event_id=eid2,
            related_ips=("10.0.0.1",),
        )
        window.add_event(entity_uuid, event1)
        window.add_event(entity_uuid, event2)

        alerts = engine.evaluate(event2, entity_refs=(entity_uuid,))
        assert len(alerts) == 1
        assert eid1 in alerts[0].contributing_events
        assert eid2 in alerts[0].contributing_events

    def test_alert_severity_from_rule(self) -> None:
        """Alert severity matches rule's alert_severity."""
        alerts = self._fire_engine()
        assert len(alerts) == 1
        assert alerts[0].severity_id == SeverityLevel.CRITICAL

    def test_alert_dedup_key_format(self) -> None:
        """Alert dedup_key follows 'corr:<rule_name>:<entity_uuid>' format."""
        alerts = self._fire_engine()
        assert len(alerts) == 1
        assert alerts[0].dedup_key.startswith("corr:alert_gen_rule:")
        assert "uuid-alert-entity" in alerts[0].dedup_key

    def test_alert_entity_uuid_set(self) -> None:
        """Alert entity_uuid matches the entity that triggered it."""
        alerts = self._fire_engine()
        assert len(alerts) == 1
        assert alerts[0].entity_uuid == "uuid-alert-entity"

    def test_alert_description_contains_rule_name(self) -> None:
        """Alert description references the rule name."""
        alerts = self._fire_engine()
        assert len(alerts) == 1
        assert "alert_gen_rule" in alerts[0].description


# ---------------------------------------------------------------------------
# Task 5 (S-042): Risk score computation tests
# ---------------------------------------------------------------------------


class TestCorrelationRiskScore:
    """Tests for risk score computation in CorrelationEngine._create_alert()."""

    def test_risk_score_based_on_rule_severity(self) -> None:
        """Higher severity rules produce higher risk scores."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-risk-entity"

        # Low severity rule (WARNING = 3)
        low_rule = _make_rule(
            name="low_sev",
            entity_type="ip",
            alert_severity=SeverityLevel.WARNING,
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "event.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )
        # High severity rule (FATAL = 6)
        high_rule = _make_rule(
            name="high_sev",
            entity_type="ip",
            alert_severity=SeverityLevel.FATAL,
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "event.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )

        event = _make_event(
            message="event detected",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )

        # Engine with low severity
        window_low = _make_window()
        engine_low = CorrelationEngine(rules=[low_rule], window=window_low)
        window_low.add_event(entity_uuid, event)
        alerts_low = engine_low.evaluate(event, entity_refs=(entity_uuid,))

        # Engine with high severity
        window_high = _make_window()
        engine_high = CorrelationEngine(rules=[high_rule], window=window_high)
        window_high.add_event(entity_uuid, event)
        alerts_high = engine_high.evaluate(event, entity_refs=(entity_uuid,))

        assert len(alerts_low) == 1
        assert len(alerts_high) == 1
        assert alerts_low[0].risk_score > 0
        assert alerts_high[0].risk_score > alerts_low[0].risk_score

    def test_risk_score_scales_with_contributing_events(self) -> None:
        """More contributing events produce higher risk score."""
        from seerflow.correlation.engine import CorrelationEngine

        now = time.time_ns()
        entity_uuid = "uuid-scale-entity"

        rule = _make_rule(
            name="scale_rule",
            entity_type="ip",
            alert_severity=SeverityLevel.ERROR,
            sources=(
                SourceCondition(
                    source_type="syslog",
                    conditions={"message": "event.*"},
                    min_count=1,
                ),
            ),
            min_sources=1,
        )

        # Scenario A: 1 contributing event
        window_a = _make_window()
        engine_a = CorrelationEngine(rules=[rule], window=window_a)
        event_a = _make_event(
            message="event detected",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window_a.add_event(entity_uuid, event_a)
        alerts_a = engine_a.evaluate(event_a, entity_refs=(entity_uuid,))

        # Scenario B: 5 contributing events
        window_b = _make_window()
        engine_b = CorrelationEngine(rules=[rule], window=window_b)
        for i in range(5):
            ev = _make_event(
                message="event detected",
                source_type="syslog",
                timestamp_ns=now - (5 - i) * 1_000_000,
                related_ips=("10.0.0.1",),
            )
            window_b.add_event(entity_uuid, ev)
        trigger_b = _make_event(
            message="event detected",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )
        window_b.add_event(entity_uuid, trigger_b)
        alerts_b = engine_b.evaluate(trigger_b, entity_refs=(entity_uuid,))

        assert len(alerts_a) == 1
        assert len(alerts_b) == 1
        assert alerts_b[0].risk_score > alerts_a[0].risk_score

    def test_risk_score_zero_for_no_contributing_events(self) -> None:
        """Edge case: if somehow no contributing events, score is 0."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            name="zero_rule",
            entity_type="ip",
            alert_severity=SeverityLevel.WARNING,
        )

        event = _make_event(
            message="test",
            source_type="syslog",
            related_ips=("10.0.0.1",),
        )

        # Call _create_alert directly with empty contributing_event_ids
        alert = CorrelationEngine._create_alert(
            rule=rule,
            entity_uuid="uuid-zero",
            trigger_event=event,
            contributing_event_ids=(),
        )
        assert alert.risk_score == 0.0

    def test_risk_score_capped_at_one(self) -> None:
        """Risk score should be in [0, 1] range even with many events + high severity."""
        from seerflow.correlation.engine import CorrelationEngine

        rule = _make_rule(
            name="cap_rule",
            entity_type="ip",
            alert_severity=SeverityLevel.FATAL,  # max severity = 6
        )

        now = time.time_ns()
        event = _make_event(
            message="test",
            source_type="syslog",
            timestamp_ns=now,
            related_ips=("10.0.0.1",),
        )

        # 50 contributing events — far above the cap of 10
        many_ids = tuple(uuid.uuid4() for _ in range(50))

        alert = CorrelationEngine._create_alert(
            rule=rule,
            entity_uuid="uuid-cap",
            trigger_event=event,
            contributing_event_ids=many_ids,
        )
        assert 0.0 <= alert.risk_score <= 1.0
