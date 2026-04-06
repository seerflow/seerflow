"""Tests for Alert, CorrelationRule, and SourceCondition structs."""

from __future__ import annotations

import uuid

import msgspec
import pytest

from seerflow.detection.ensemble import DetectionResult
from seerflow.models.alert import (
    Alert,
    CorrelationRule,
    SourceCondition,
)
from seerflow.models.event import SeerflowEvent, SeverityLevel


class TestAlertCreation:
    def test_create_with_required_fields(self) -> None:
        alert = Alert(
            alert_id="alert-001",
            alert_type="ml",
            timestamp_ns=1_000_000_000,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst_content_anomaly",
            description="Content anomaly detected",
            entity_uuid="ent-uuid-1",
            entity_value="192.168.1.1",
            entity_type="ip",
            contributing_events=(uuid.uuid4(),),
        )
        assert alert.alert_id == "alert-001"
        assert alert.alert_type == "ml"
        assert alert.severity_id == SeverityLevel.WARNING
        # Check defaults
        assert alert.mitre_tactics == ()
        assert alert.mitre_techniques == ()
        assert alert.risk_score == 0.0
        assert alert.dedup_key == ""
        assert alert.dedup_count == 1
        assert alert.feedback == ""

    def test_create_with_all_fields(self) -> None:
        eid = uuid.uuid4()
        alert = Alert(
            alert_id="alert-002",
            alert_type="sigma",
            timestamp_ns=2_000_000_000,
            severity_id=SeverityLevel.CRITICAL,
            rule_name="sigma_brute_force",
            description="Brute force detected",
            entity_uuid="ent-uuid-2",
            entity_value="admin",
            entity_type="user",
            contributing_events=(eid,),
            mitre_tactics=("TA0006",),
            mitre_techniques=("T1110",),
            risk_score=0.95,
            dedup_key="sigma:brute_force:ent-uuid-2",
            dedup_count=5,
            feedback="tp",
        )
        assert alert.alert_type == "sigma"
        assert alert.severity_id == SeverityLevel.CRITICAL
        assert alert.mitre_tactics == ("TA0006",)
        assert alert.risk_score == 0.95
        assert alert.dedup_count == 5
        assert alert.feedback == "tp"
        assert alert.contributing_events == (eid,)


class TestAlertImmutability:
    def test_frozen_rejects_assignment(self) -> None:
        alert = Alert(
            alert_id="a1",
            alert_type="ml",
            timestamp_ns=1,
            severity_id=SeverityLevel.INFORMATIONAL,
            rule_name="r",
            description="d",
            entity_uuid="e",
            entity_value="v",
            entity_type="ip",
            contributing_events=(),
        )
        with pytest.raises(AttributeError):
            alert.risk_score = 1.0  # type: ignore[misc]


class TestAlertSerialization:
    def _make_alert(self) -> Alert:
        return Alert(
            alert_id="a1",
            alert_type="correlation",
            timestamp_ns=1_000,
            severity_id=SeverityLevel.ERROR,
            rule_name="exfiltration",
            description="Data exfiltration detected",
            entity_uuid="uuid-1",
            entity_value="admin",
            entity_type="user",
            contributing_events=(uuid.uuid4(), uuid.uuid4()),
            mitre_tactics=("TA0010",),
            risk_score=0.8,
        )

    def test_msgpack_roundtrip(self) -> None:
        alert = self._make_alert()
        encoded = msgspec.msgpack.encode(alert)
        decoded = msgspec.msgpack.decode(encoded, type=Alert)
        assert decoded == alert

    def test_json_roundtrip(self) -> None:
        alert = self._make_alert()
        encoded = msgspec.json.encode(alert)
        decoded = msgspec.json.decode(encoded, type=Alert)
        assert decoded == alert


class TestAlertValidation:
    def test_invalid_alert_type_rejected(self) -> None:
        bad_json = (
            b'{"alert_id":"a","alert_type":"invalid","timestamp_ns":1,'
            b'"severity_id":1,"rule_name":"r","description":"d",'
            b'"entity_uuid":"e","entity_value":"v","entity_type":"ip",'
            b'"contributing_events":[]}'
        )
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad_json, type=Alert)

    def test_invalid_severity_rejected(self) -> None:
        bad_json = (
            b'{"alert_id":"a","alert_type":"ml","timestamp_ns":1,'
            b'"severity_id":99,"rule_name":"r","description":"d",'
            b'"entity_uuid":"e","entity_value":"v","entity_type":"ip",'
            b'"contributing_events":[]}'
        )
        with pytest.raises(msgspec.ValidationError):
            msgspec.json.decode(bad_json, type=Alert)


class TestCorrelationRule:
    def test_create_with_source_conditions(self) -> None:
        cond1 = SourceCondition(
            source_type="syslog",
            conditions={"message": "failed.*login"},
            min_count=3,
        )
        cond2 = SourceCondition(
            source_type="otlp",
            conditions={"event_action": "smb_connect"},
        )
        rule = CorrelationRule(
            name="brute_force_lateral",
            entity_type="user",
            window_seconds=1800,
            sources=(cond1, cond2),
            min_sources=2,
            alert_severity=SeverityLevel.CRITICAL,
            mitre_tactics=("TA0006", "TA0008"),
            mitre_techniques=("T1110", "T1021"),
            description="Brute force followed by lateral movement",
        )
        assert rule.name == "brute_force_lateral"
        assert rule.window_seconds == 1800
        assert len(rule.sources) == 2
        assert rule.sources[0].source_type == "syslog"
        assert rule.sources[0].min_count == 3
        assert rule.min_sources == 2
        assert rule.alert_severity == SeverityLevel.CRITICAL
        assert rule.description == "Brute force followed by lateral movement"

    def test_msgpack_roundtrip(self) -> None:
        rule = CorrelationRule(
            name="test_rule",
            entity_type="ip",
            window_seconds=600,
            sources=(SourceCondition(source_type="syslog", conditions={"msg": ".*"}),),
            min_sources=1,
            alert_severity=SeverityLevel.WARNING,
        )
        encoded = msgspec.msgpack.encode(rule)
        decoded = msgspec.msgpack.decode(encoded, type=CorrelationRule)
        assert decoded == rule


class TestCorrelationRuleValidation:
    def test_negative_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            CorrelationRule(
                name="bad",
                entity_type="ip",
                window_seconds=-1,
                sources=(SourceCondition(source_type="x", conditions={}),),
                min_sources=1,
                alert_severity=SeverityLevel.WARNING,
            )

    def test_zero_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            CorrelationRule(
                name="bad",
                entity_type="ip",
                window_seconds=0,
                sources=(SourceCondition(source_type="x", conditions={}),),
                min_sources=1,
                alert_severity=SeverityLevel.WARNING,
            )

    def test_min_sources_exceeds_sources_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"min_sources.*cannot exceed"):
            CorrelationRule(
                name="bad",
                entity_type="ip",
                window_seconds=60,
                sources=(SourceCondition(source_type="x", conditions={}),),
                min_sources=5,
                alert_severity=SeverityLevel.WARNING,
            )

    def test_min_sources_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="min_sources must be >= 1"):
            CorrelationRule(
                name="bad",
                entity_type="ip",
                window_seconds=60,
                sources=(SourceCondition(source_type="x", conditions={}),),
                min_sources=0,
                alert_severity=SeverityLevel.WARNING,
            )


class TestSourceCondition:
    def test_create_with_defaults(self) -> None:
        cond = SourceCondition(
            source_type="file",
            conditions={"path": "/var/log/auth.log"},
        )
        assert cond.source_type == "file"
        assert cond.conditions == {"path": "/var/log/auth.log"}
        assert cond.min_count == 1  # default

    def test_frozen(self) -> None:
        cond = SourceCondition(source_type="x", conditions={})
        with pytest.raises(AttributeError):
            cond.source_type = "y"  # type: ignore[misc]


class TestCreateMlAlert:
    """Tests for create_ml_alert factory function."""

    def _make_event(
        self,
        *,
        template_id: int = 5,
        source_type: str = "syslog",
        timestamp_ns: int = 1_700_000_000_000_000_000,
        severity_id: SeverityLevel = SeverityLevel.ERROR,
        entity_refs: tuple[str, ...] = ("uuid-ip-placeholder", "uuid-user-placeholder"),
        related_ips: tuple[str, ...] = ("192.168.1.1",),
        related_users: tuple[str, ...] = ("root",),
        related_hosts: tuple[str, ...] = (),
    ) -> SeerflowEvent:
        return SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=timestamp_ns,
            observed_ns=timestamp_ns + 1000,
            severity_id=severity_id,
            message="test anomaly event",
            source_type=source_type,
            template_id=template_id,
            entity_refs=entity_refs,
            related_ips=related_ips,
            related_users=related_users,
            related_hosts=related_hosts,
        )

    def _make_result(
        self,
        *,
        score: float = 0.85,
        upper_threshold: float = 0.70,
        is_anomaly: bool = True,
        anomaly_direction: str = "upper",
    ) -> DetectionResult:
        return DetectionResult(
            score=score,
            upper_threshold=upper_threshold,
            lower_threshold=0.1,
            is_anomaly=is_anomaly,
            anomaly_direction=anomaly_direction,
            source_type="syslog",
        )

    def test_creates_alert_with_correct_fields(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event()
        result = self._make_result()
        alert = create_ml_alert(event, result)

        assert alert.alert_type == "ml"
        assert alert.rule_name == "hst-anomaly"
        assert alert.timestamp_ns == event.timestamp_ns
        assert alert.severity_id == event.severity_id
        assert alert.risk_score == result.score
        assert alert.contributing_events == (event.event_id,)
        assert "0.850" in alert.description
        assert "0.700" in alert.description
        assert "upper" in alert.description

    def test_alert_id_is_uuid5_format(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event()
        result = self._make_result()
        alert = create_ml_alert(event, result)

        parsed = uuid.UUID(alert.alert_id)
        assert parsed.version == 5

    def test_alert_id_is_deterministic(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event()
        result = self._make_result()
        alert1 = create_ml_alert(event, result)
        alert2 = create_ml_alert(event, result)

        assert alert1.alert_id == alert2.alert_id

    def test_dedup_key_format(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event(template_id=42, source_type="otlp")
        result = self._make_result()
        alert = create_ml_alert(event, result)

        assert alert.dedup_key == "hst:42:otlp"

    def test_empty_entity_refs(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event(
            entity_refs=(),
            related_ips=(),
            related_users=(),
            related_hosts=(),
        )
        result = self._make_result()
        alert = create_ml_alert(event, result)

        assert alert.entity_uuid == ""
        assert alert.entity_value == ""
        assert alert.entity_type == "ip"  # fallback

    def test_risk_score_clamped_to_valid_range(self) -> None:
        """risk_score > 1.0 is clamped to 1.0."""
        from seerflow.models.alert import create_ml_alert

        result = self._make_result(score=1.5)
        event = self._make_event()
        alert = create_ml_alert(event, result)
        assert alert.risk_score == 1.0

    def test_risk_score_negative_clamped_to_zero(self) -> None:
        """risk_score < 0.0 is clamped to 0.0."""
        from seerflow.models.alert import create_ml_alert

        result = self._make_result(score=-0.5)
        event = self._make_event()
        alert = create_ml_alert(event, result)
        assert alert.risk_score == 0.0

    def test_first_entity_used(self) -> None:
        from seerflow.models.alert import create_ml_alert

        event = self._make_event(
            entity_refs=("uuid-ip", "uuid-user", "uuid-host"),
            related_ips=("10.0.0.1",),
            related_users=("admin",),
            related_hosts=("web01",),
        )
        result = self._make_result()
        alert = create_ml_alert(event, result)

        assert alert.entity_uuid == "uuid-ip"  # UUID5 from entity_refs
        assert alert.entity_value == "10.0.0.1"  # raw from related_ips
        assert alert.entity_type == "ip"  # inferred


class TestCreateMlAlerts:
    """Tests for create_ml_alerts factory function (per-entity granularity)."""

    def _make_event(
        self,
        *,
        template_id: int = 5,
        source_type: str = "syslog",
        timestamp_ns: int = 1_700_000_000_000_000_000,
        severity_id: SeverityLevel = SeverityLevel.ERROR,
        related_ips: tuple[str, ...] = ("192.168.1.1",),
        related_users: tuple[str, ...] = ("root",),
        related_hosts: tuple[str, ...] = ("web01",),
    ) -> SeerflowEvent:
        return SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=timestamp_ns,
            observed_ns=timestamp_ns + 1000,
            severity_id=severity_id,
            message="test anomaly event",
            source_type=source_type,
            template_id=template_id,
            related_ips=related_ips,
            related_users=related_users,
            related_hosts=related_hosts,
        )

    def _make_result(
        self,
        *,
        score: float = 0.85,
        upper_threshold: float = 0.70,
    ) -> DetectionResult:
        return DetectionResult(
            score=score,
            upper_threshold=upper_threshold,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )

    def test_multi_entity_creates_multiple_alerts(self) -> None:
        """Three typed entities produce three alerts."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        user_uuid = str(uuid.uuid4())
        host_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("192.168.1.1",),
            related_users=("root",),
            related_hosts=("web01",),
        )
        typed_entities = [
            ("ip", ip_uuid),
            ("user", user_uuid),
            ("host", host_uuid),
        ]
        alerts = create_ml_alerts(event, self._make_result(), typed_entities)

        assert len(alerts) == 3
        assert alerts[0].entity_uuid == ip_uuid
        assert alerts[0].entity_type == "ip"
        assert alerts[1].entity_uuid == user_uuid
        assert alerts[1].entity_type == "user"
        assert alerts[2].entity_uuid == host_uuid
        assert alerts[2].entity_type == "host"

    def test_single_entity_creates_one_alert(self) -> None:
        """One typed entity produces one alert (no regression)."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("10.0.0.1",),
            related_users=(),
            related_hosts=(),
        )
        alerts = create_ml_alerts(event, self._make_result(), [("ip", ip_uuid)])

        assert len(alerts) == 1
        assert alerts[0].entity_uuid == ip_uuid
        assert alerts[0].entity_type == "ip"
        assert alerts[0].entity_value == "10.0.0.1"

    def test_zero_entities_creates_one_fallback_alert(self) -> None:
        """No typed entities produces one fallback alert via create_ml_alert."""
        from seerflow.models.alert import create_ml_alerts

        event = self._make_event()
        alerts = create_ml_alerts(event, self._make_result(), [])

        assert len(alerts) == 1
        assert alerts[0].alert_type == "ml"

    def test_alert_ids_unique_per_entity(self) -> None:
        """Each alert in the list has a different alert_id."""
        from seerflow.models.alert import create_ml_alerts

        uuid1 = str(uuid.uuid4())
        uuid2 = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("1.2.3.4",),
            related_users=("alice",),
            related_hosts=(),
        )
        alerts = create_ml_alerts(event, self._make_result(), [("ip", uuid1), ("user", uuid2)])

        assert alerts[0].alert_id != alerts[1].alert_id

    def test_dedup_keys_include_entity_uuid(self) -> None:
        """Each alert's dedup_key contains its entity UUID."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        user_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("1.2.3.4",),
            related_users=("bob",),
            related_hosts=(),
        )
        alerts = create_ml_alerts(
            event, self._make_result(), [("ip", ip_uuid), ("user", user_uuid)]
        )

        assert ip_uuid in alerts[0].dedup_key
        assert user_uuid in alerts[1].dedup_key

    def test_entity_value_mapped_from_related_fields(self) -> None:
        """Raw entity values are resolved from related_* fields by type."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        user_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("172.16.0.1",),
            related_users=("jsmith",),
            related_hosts=(),
        )
        alerts = create_ml_alerts(
            event, self._make_result(), [("ip", ip_uuid), ("user", user_uuid)]
        )

        assert alerts[0].entity_value == "172.16.0.1"
        assert alerts[1].entity_value == "jsmith"

    def test_all_alerts_share_same_timestamp_and_severity(self) -> None:
        """Timestamp and severity come from the event for all alerts."""
        from seerflow.models.alert import create_ml_alerts

        uuid1 = str(uuid.uuid4())
        uuid2 = str(uuid.uuid4())
        ts = 9_999_000_000_000_000_000
        event = self._make_event(
            timestamp_ns=ts,
            severity_id=SeverityLevel.CRITICAL,
            related_ips=("1.1.1.1",),
            related_users=("admin",),
            related_hosts=(),
        )
        alerts = create_ml_alerts(event, self._make_result(), [("ip", uuid1), ("user", uuid2)])

        for alert in alerts:
            assert alert.timestamp_ns == ts
            assert alert.severity_id == SeverityLevel.CRITICAL

    def test_alert_ids_are_uuid5(self) -> None:
        """Each alert_id is a valid UUID5 string."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("5.5.5.5",),
            related_users=(),
            related_hosts=(),
        )
        alerts = create_ml_alerts(event, self._make_result(), [("ip", ip_uuid)])

        parsed = uuid.UUID(alerts[0].alert_id)
        assert parsed.version == 5

    def test_description_contains_score_and_threshold(self) -> None:
        """Alert description contains score and threshold values."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        event = self._make_event(related_ips=("1.2.3.4",), related_users=(), related_hosts=())
        result = self._make_result(score=0.92, upper_threshold=0.75)
        alerts = create_ml_alerts(event, result, [("ip", ip_uuid)])

        assert "0.920" in alerts[0].description
        assert "0.750" in alerts[0].description
        assert "direction=" in alerts[0].description

    def test_more_entities_than_raw_values_falls_back_to_empty(self) -> None:
        """Entity with no corresponding raw value gets empty string."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid1 = str(uuid.uuid4())
        ip_uuid2 = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("1.2.3.4",),
            related_users=(),
            related_hosts=(),
        )
        alerts = create_ml_alerts(event, self._make_result(), [("ip", ip_uuid1), ("ip", ip_uuid2)])
        assert len(alerts) == 2
        assert alerts[0].entity_value == "1.2.3.4"
        assert alerts[1].entity_value == ""

    def test_unknown_entity_type_skipped(self) -> None:
        """Unknown entity_type is skipped with a warning; only valid entities produce alerts."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        bogus_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("10.0.0.1",),
            related_users=(),
            related_hosts=(),
        )
        typed_entities = [("ip", ip_uuid), ("bogus", bogus_uuid)]
        alerts = create_ml_alerts(event, self._make_result(), typed_entities)

        assert len(alerts) == 1
        assert alerts[0].entity_type == "ip"
        assert alerts[0].entity_uuid == ip_uuid

    def test_unknown_entity_type_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown entity_type emits a WARNING log mentioning the bad type."""
        import logging

        from seerflow.models.alert import create_ml_alerts

        bogus_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=(),
            related_users=(),
            related_hosts=(),
        )
        with caplog.at_level(logging.WARNING, logger="seerflow.models.alert"):
            alerts = create_ml_alerts(event, self._make_result(), [("bogus", bogus_uuid)])

        assert len(alerts) == 0
        assert "bogus" in caplog.text

    def test_risk_score_clamped_in_multi_entity(self) -> None:
        """risk_score > 1.0 is clamped to 1.0 in per-entity alerts."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        event = self._make_event(related_ips=("10.0.0.1",), related_users=(), related_hosts=())
        result = self._make_result(score=2.3)
        alerts = create_ml_alerts(event, result, [("ip", ip_uuid)])

        assert len(alerts) == 1
        assert alerts[0].risk_score == 1.0

    def test_risk_score_negative_clamped_in_multi_entity(self) -> None:
        """risk_score < 0.0 is clamped to 0.0 in per-entity alerts."""
        from seerflow.models.alert import create_ml_alerts

        ip_uuid = str(uuid.uuid4())
        event = self._make_event(related_ips=("10.0.0.1",), related_users=(), related_hosts=())
        result = self._make_result(score=-1.0)
        alerts = create_ml_alerts(event, result, [("ip", ip_uuid)])

        assert len(alerts) == 1
        assert alerts[0].risk_score == 0.0

    def test_duplicate_uuid_preserves_both_values(self) -> None:
        """Two entities sharing the same UUID get correct raw values (no overwrite)."""
        from seerflow.models.alert import create_ml_alerts

        shared_uuid = str(uuid.uuid4())
        event = self._make_event(
            related_ips=("10.0.0.1", "10.0.0.2"),
            related_users=(),
            related_hosts=(),
        )
        alerts = create_ml_alerts(
            event, self._make_result(), [("ip", shared_uuid), ("ip", shared_uuid)]
        )
        assert len(alerts) == 2
        assert alerts[0].entity_uuid == shared_uuid
        assert alerts[1].entity_uuid == shared_uuid
        assert alerts[0].entity_value == "10.0.0.1"
        assert alerts[1].entity_value == "10.0.0.2"
