"""Tests for Pydantic API response/request models."""

from __future__ import annotations

import uuid

import pytest

from seerflow.api.schemas import (
    AlertResponse,
    EntitySearchResult,
    EventResponse,
    FeedbackRequest,
    HealthResponse,
    PaginatedResponse,
    StatsResponse,
)
from seerflow.models.event import SeerflowEvent


class TestEventResponse:
    """Tests for EventResponse and from_event conversion."""

    def test_from_event_converts_fields(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_000_000_000,
            observed_ns=1_000_000_001,
            message="test log line",
            source_type="syslog",
            entity_refs=("ref1", "ref2"),
        )
        resp = EventResponse.from_event(event)
        assert resp.event_id == str(event.event_id)
        assert resp.timestamp_ns == 1_000_000_000
        assert resp.observed_ns == 1_000_000_001
        assert resp.message == "test log line"
        assert resp.source_type == "syslog"
        assert resp.entity_refs == ["ref1", "ref2"]

    def test_from_event_defaults(self) -> None:
        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=0,
            observed_ns=0,
        )
        resp = EventResponse.from_event(event)
        assert resp.severity_text == "Informational"
        assert resp.entity_refs == []


class TestAlertResponse:
    """Tests for AlertResponse and from_alert conversion."""

    def test_from_alert_converts_fields(self) -> None:
        from seerflow.models.alert import Alert

        alert = Alert(
            alert_id="abc-123",
            alert_type="ml",
            timestamp_ns=2_000_000_000,
            severity_id=4,
            rule_name="hst_anomaly",
            description="Anomaly detected",
            entity_uuid="ent-456",
            entity_value="192.168.1.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
            risk_score=0.85,
            dedup_count=3,
            mitre_tactics=("initial-access",),
            mitre_techniques=("T1190",),
        )
        resp = AlertResponse.from_alert(alert)
        assert resp.alert_id == "abc-123"
        assert resp.alert_type == "ml"
        assert resp.severity == 4
        assert resp.risk_score == 0.85
        assert resp.entity_uuid == "ent-456"
        assert resp.entity_value == "192.168.1.1"
        assert resp.entity_type == "ip"
        assert resp.message == "Anomaly detected"
        assert resp.dedup_count == 3
        assert resp.mitre_tactics == ["initial-access"]
        assert resp.mitre_techniques == ["T1190"]

    def test_from_alert_no_mitre(self) -> None:
        from seerflow.models.alert import Alert

        alert = Alert(
            alert_id="abc-123",
            alert_type="sigma",
            timestamp_ns=0,
            severity_id=3,
            rule_name="sigma_rule",
            description="Sigma match",
            entity_uuid="ent-789",
            entity_value="admin",
            entity_type="user",
            contributing_events=(),
        )
        resp = AlertResponse.from_alert(alert)
        assert resp.mitre_tactics == []
        assert resp.mitre_techniques == []


class TestFeedbackRequest:
    """Tests for feedback request validation."""

    def test_valid_tp(self) -> None:
        req = FeedbackRequest(feedback="tp")
        assert req.feedback == "tp"

    def test_valid_fp(self) -> None:
        req = FeedbackRequest(feedback="fp")
        assert req.feedback == "fp"

    def test_invalid_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            FeedbackRequest(feedback="invalid")


class TestPaginatedResponse:
    """Tests for the generic paginated wrapper."""

    def test_has_next_true(self) -> None:
        resp = PaginatedResponse[str](
            items=["a", "b"],
            total=10,
            page=1,
            limit=2,
            has_next=True,
        )
        assert resp.has_next is True

    def test_has_next_false(self) -> None:
        resp = PaginatedResponse[str](
            items=["a", "b"],
            total=2,
            page=1,
            limit=2,
            has_next=False,
        )
        assert resp.has_next is False


class TestHealthResponse:
    """Tests for health response model."""

    def test_healthy_status(self) -> None:
        resp = HealthResponse(status="healthy", components={"pipeline": "running"})
        assert resp.status == "healthy"

    def test_degraded_status(self) -> None:
        resp = HealthResponse(status="degraded", components={"storage": "error"})
        assert resp.status == "degraded"


class TestStatsResponse:
    """Tests for stats response model."""

    def test_basic_stats(self) -> None:
        resp = StatsResponse(
            total_events=1000,
            total_alerts=42,
            alerts_by_severity={"critical": 2, "high": 10},
            feedback_stats={"tp": 5, "fp": 3},
        )
        assert resp.total_events == 1000
        assert resp.total_alerts == 42


class TestEntitySearchResult:
    """Tests for entity search result model."""

    def test_basic_result(self) -> None:
        result = EntitySearchResult(
            entity_type="ip",
            entity_value="10.0.0.1",
            entity_uuid="00000000-0000-0000-0000-000000000001",
        )
        assert result.entity_type == "ip"


def test_entity_relation_response_from_relation() -> None:
    from seerflow.api.schemas import EntityRelationResponse
    from seerflow.models.query import EntityRelation

    relation = EntityRelation(
        entity_uuid="abc-123",
        entity_type="host",
        entity_value="web-01",
        relation_type="communicates_with",
    )
    resp = EntityRelationResponse.from_relation(relation)
    assert resp.entity_uuid == "abc-123"
    assert resp.entity_type == "host"
    assert resp.entity_value == "web-01"
    assert resp.relation_type == "communicates_with"


def test_entity_search_result_requires_entity_uuid() -> None:
    from seerflow.api.schemas import EntitySearchResult

    result = EntitySearchResult(
        entity_type="ip",
        entity_value="10.0.0.1",
        entity_uuid="3e1b9c5c-8f3e-5a0e-9d2a-8b1e6f0a1234",
    )
    assert result.entity_uuid == "3e1b9c5c-8f3e-5a0e-9d2a-8b1e6f0a1234"
    dumped = result.model_dump()
    assert dumped == {
        "entity_type": "ip",
        "entity_value": "10.0.0.1",
        "entity_uuid": "3e1b9c5c-8f3e-5a0e-9d2a-8b1e6f0a1234",
    }


def test_entity_timeline_response_envelope() -> None:
    from seerflow.api.schemas import (
        EntityRelationResponse,
        EntityTimelineResponse,
        EventResponse,
    )

    event = EventResponse(
        event_id="abc",
        timestamp_ns=1_775_736_000_000_000_000,
        observed_ns=1_775_736_000_000_000_001,
        severity_id=3,
        severity_text="INFO",
        source_type="syslog",
        message="hi",
        template_id=-1,
        entity_refs=[],
    )
    relation = EntityRelationResponse(
        entity_uuid="abc",
        entity_type="ip",
        entity_value="10.0.0.1",
        relation_type="seen_on",
    )
    envelope = EntityTimelineResponse(
        entity_uuid="3e1b9c5c-8f3e-5a0e-9d2a-8b1e6f0a1234",
        events=[event],
        related=[relation],
        total=1,
    )
    assert envelope.total == 1
    assert envelope.events[0].message == "hi"
    assert envelope.related[0].relation_type == "seen_on"


class TestAttackCoverageSchemas:
    def test_attack_coverage_cell_roundtrip(self) -> None:
        from seerflow.api.schemas import AttackCoverageCell

        cell = AttackCoverageCell(
            tactic="discovery",
            technique="T1033",
            rule_count=2,
            alert_count=1,
            covered=True,
            detected=True,
        )
        assert cell.model_dump() == {
            "tactic": "discovery",
            "technique": "T1033",
            "rule_count": 2,
            "alert_count": 1,
            "covered": True,
            "detected": True,
        }

    def test_attack_coverage_tactic_default_techniques_empty(self) -> None:
        from seerflow.api.schemas import AttackCoverageTactic

        tactic = AttackCoverageTactic(
            tactic="discovery", tactic_display_name="Discovery (TA0007)"
        )
        assert tactic.techniques == []

    def test_attack_coverage_response_empty_ok(self) -> None:
        from seerflow.api.schemas import (
            AttackCoverageResponse,
            AttackCoverageSummary,
        )

        resp = AttackCoverageResponse(
            window_since="2026-03-12T00:00:00+00:00",
            window_until="2026-04-11T00:00:00+00:00",
            tactics=[],
            summary=AttackCoverageSummary(
                total_techniques_covered=0,
                total_techniques_detected=0,
                total_rules_with_attack_tags=0,
                total_alerts_matched=0,
            ),
        )
        body = resp.model_dump()
        assert body["summary"]["total_techniques_covered"] == 0
        assert body["tactics"] == []
