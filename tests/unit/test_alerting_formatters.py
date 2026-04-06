"""Tests for alert formatters: Slack Block Kit, Teams Adaptive Card, and JSON."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from seerflow.alerting.formatters import format_json, format_slack, format_teams
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(
    *,
    alert_id: str = "550e8400-e29b-41d4-a716-446655440000",
    alert_type: str = "ml",
    timestamp_ns: int = 1_700_000_000_000_000_000,
    severity_id: SeverityLevel = SeverityLevel.WARNING,
    rule_name: str = "test-rule",
    description: str = "Test alert description",
    entity_uuid: str = "entity-uuid-001",
    entity_value: str = "192.168.1.1",
    entity_type: str = "ip",
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
    risk_score: float = 0.75,
    dedup_key: str = "test:dedup:key",
    dedup_count: int = 1,
) -> Alert:
    """Return a default Alert instance for testing."""
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=timestamp_ns,
        severity_id=severity_id,
        rule_name=rule_name,
        description=description,
        entity_uuid=entity_uuid,
        entity_value=entity_value,
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(uuid.UUID("12345678-1234-5678-1234-567812345678"),),
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
        risk_score=risk_score,
        dedup_key=dedup_key,
        dedup_count=dedup_count,
    )


class TestFormatSlack:
    def test_contains_severity_and_rule(self) -> None:
        alert = _make_alert(severity_id=SeverityLevel.ERROR, rule_name="hst-anomaly")
        payload = format_slack(alert)
        text = str(payload)
        assert "hst-anomaly" in text
        assert "blocks" in payload

    def test_includes_mitre_when_present(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0001",), mitre_techniques=("T1078",))
        payload = format_slack(alert)
        text = str(payload)
        assert "TA0001" in text
        assert "T1078" in text

    def test_no_mitre_section_when_empty(self) -> None:
        alert = _make_alert(mitre_tactics=(), mitre_techniques=())
        payload = format_slack(alert)
        text = str(payload)
        assert "TA0001" not in text
        assert "T1078" not in text

    def test_blocks_is_list(self) -> None:
        alert = _make_alert()
        payload = format_slack(alert)
        assert isinstance(payload["blocks"], list)
        assert len(payload["blocks"]) > 0

    def test_contains_entity_value(self) -> None:
        alert = _make_alert(entity_value="10.0.0.1", entity_type="ip")
        payload = format_slack(alert)
        text = str(payload)
        assert "10.0.0.1" in text

    def test_contains_description(self) -> None:
        alert = _make_alert(description="Suspicious login detected")
        payload = format_slack(alert)
        text = str(payload)
        assert "Suspicious login detected" in text

    def test_severity_label_in_header(self) -> None:
        alert = _make_alert(severity_id=SeverityLevel.CRITICAL)
        payload = format_slack(alert)
        text = str(payload)
        assert "CRITICAL" in text or "Critical" in text

    def test_json_serializable(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0003",), mitre_techniques=("T1059",))
        payload = format_slack(alert)
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)

    def test_returns_dict(self) -> None:
        alert = _make_alert()
        payload = format_slack(alert)
        assert isinstance(payload, dict)

    def test_dedup_count_above_one_shown(self) -> None:
        alert = _make_alert(dedup_count=5)
        payload = format_slack(alert)
        text = str(payload)
        assert "5" in text

    def test_risk_score_shown(self) -> None:
        alert = _make_alert(risk_score=0.92)
        payload = format_slack(alert)
        text = str(payload)
        assert "0.92" in text

    def test_multiple_mitre_tactics(self) -> None:
        alert = _make_alert(
            mitre_tactics=("TA0001", "TA0003"),
            mitre_techniques=("T1078", "T1059"),
        )
        payload = format_slack(alert)
        text = str(payload)
        assert "TA0001" in text
        assert "TA0003" in text
        assert "T1078" in text
        assert "T1059" in text


class TestFormatTeams:
    def test_contains_adaptive_card(self) -> None:
        alert = _make_alert()
        payload = format_teams(alert)
        assert payload["type"] == "message"
        assert "attachments" in payload

    def test_attachments_has_adaptive_card_content_type(self) -> None:
        alert = _make_alert()
        payload = format_teams(alert)
        attachments = payload["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["contentType"] == "application/vnd.microsoft.card.adaptive"

    def test_adaptive_card_has_body(self) -> None:
        alert = _make_alert()
        payload = format_teams(alert)
        card = payload["attachments"][0]["content"]
        assert "body" in card
        assert isinstance(card["body"], list)

    def test_contains_rule_name(self) -> None:
        alert = _make_alert(rule_name="sigma-brute-force")
        payload = format_teams(alert)
        text = str(payload)
        assert "sigma-brute-force" in text

    def test_contains_severity(self) -> None:
        alert = _make_alert(severity_id=SeverityLevel.CRITICAL)
        payload = format_teams(alert)
        text = str(payload)
        assert "CRITICAL" in text or "Critical" in text

    def test_contains_entity_value(self) -> None:
        alert = _make_alert(entity_value="admin-user", entity_type="user")
        payload = format_teams(alert)
        text = str(payload)
        assert "admin-user" in text

    def test_includes_mitre_when_present(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0006",), mitre_techniques=("T1110",))
        payload = format_teams(alert)
        text = str(payload)
        assert "TA0006" in text
        assert "T1110" in text

    def test_json_serializable(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0001",))
        payload = format_teams(alert)
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)

    def test_returns_dict(self) -> None:
        alert = _make_alert()
        payload = format_teams(alert)
        assert isinstance(payload, dict)

    def test_card_schema_version_present(self) -> None:
        alert = _make_alert()
        payload = format_teams(alert)
        card = payload["attachments"][0]["content"]
        assert card.get("$schema") or card.get("version")


class TestFormatJson:
    def test_contains_all_alert_fields(self) -> None:
        alert = _make_alert()
        payload = format_json(alert)
        assert "alert_id" in payload
        assert "severity" in payload
        assert "timestamp" in payload

    def test_timestamp_is_iso8601(self) -> None:
        alert = _make_alert(timestamp_ns=1_700_000_000_000_000_000)
        payload = format_json(alert)
        ts = payload["timestamp"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None
        assert parsed.tzinfo == UTC

    def test_timestamp_value_correct(self) -> None:
        ts_ns = 1_700_000_000_000_000_000
        alert = _make_alert(timestamp_ns=ts_ns)
        payload = format_json(alert)
        expected_dt = datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)
        assert payload["timestamp"] == expected_dt.isoformat()

    def test_severity_is_string_name(self) -> None:
        alert = _make_alert(severity_id=SeverityLevel.CRITICAL)
        payload = format_json(alert)
        assert isinstance(payload["severity"], str)
        assert payload["severity"].isupper() or payload["severity"].istitle()

    def test_severity_name_matches_enum(self) -> None:
        alert = _make_alert(severity_id=SeverityLevel.ERROR)
        payload = format_json(alert)
        assert payload["severity"] == "ERROR"

    def test_alert_type_included(self) -> None:
        alert = _make_alert(alert_type="sigma")
        payload = format_json(alert)
        assert payload["alert_type"] == "sigma"

    def test_entity_fields_included(self) -> None:
        alert = _make_alert(entity_uuid="test-uuid", entity_value="10.0.0.1", entity_type="ip")
        payload = format_json(alert)
        assert payload["entity_uuid"] == "test-uuid"
        assert payload["entity_value"] == "10.0.0.1"
        assert payload["entity_type"] == "ip"

    def test_mitre_fields_are_lists(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0001", "TA0003"), mitre_techniques=("T1078",))
        payload = format_json(alert)
        assert isinstance(payload["mitre_tactics"], list)
        assert isinstance(payload["mitre_techniques"], list)
        assert payload["mitre_tactics"] == ["TA0001", "TA0003"]
        assert payload["mitre_techniques"] == ["T1078"]

    def test_mitre_fields_empty_lists_when_none(self) -> None:
        alert = _make_alert(mitre_tactics=(), mitre_techniques=())
        payload = format_json(alert)
        assert payload["mitre_tactics"] == []
        assert payload["mitre_techniques"] == []

    def test_risk_score_included(self) -> None:
        alert = _make_alert(risk_score=0.88)
        payload = format_json(alert)
        assert payload["risk_score"] == pytest.approx(0.88)

    def test_rule_name_included(self) -> None:
        alert = _make_alert(rule_name="custom-rule-123")
        payload = format_json(alert)
        assert payload["rule_name"] == "custom-rule-123"

    def test_description_included(self) -> None:
        alert = _make_alert(description="Detailed alert description")
        payload = format_json(alert)
        assert payload["description"] == "Detailed alert description"

    def test_json_serializable(self) -> None:
        alert = _make_alert(mitre_tactics=("TA0001",), mitre_techniques=("T1078",))
        payload = format_json(alert)
        serialized = json.dumps(payload)
        assert isinstance(serialized, str)

    def test_returns_dict(self) -> None:
        alert = _make_alert()
        payload = format_json(alert)
        assert isinstance(payload, dict)

    def test_alert_id_matches(self) -> None:
        alert = _make_alert(alert_id="my-alert-id-001")
        payload = format_json(alert)
        assert payload["alert_id"] == "my-alert-id-001"
