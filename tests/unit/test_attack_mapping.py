"""Tests for MITRE ATT&CK template-to-tactic mapping."""

from __future__ import annotations

import pytest


class TestAttackMapper:
    def test_lookup_returns_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, techniques = mapper.lookup("sshd error: maximum authentication failed for user")
        assert tactics == ("credential-access",)
        assert techniques == ("T1110",)

    def test_lookup_returns_empty_on_no_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, techniques = mapper.lookup("normal log message about disk usage")
        assert tactics == ()
        assert techniques == ()

    def test_lookup_returns_first_match(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="ssh",
                    tactics=["initial-access"],
                    techniques=["T1078"],
                ),
                AttackMapping.from_raw(
                    pattern="ssh.*failed",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                ),
            ]
        )
        tactics, _ = mapper.lookup("ssh failed login")
        assert tactics == ("initial-access",)

    def test_empty_mapper_returns_empty(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper([])
        assert mapper.lookup("anything") == ((), ())

    def test_from_config_parses_raw_dicts(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        raw = [
            {
                "pattern": "sudo.*incorrect",
                "tactics": ["privilege-escalation"],
                "techniques": ["T1548"],
            }
        ]
        mapper = AttackMapper.from_config(raw)
        tactics, _techniques = mapper.lookup("sudo: 3 incorrect password attempts")
        assert tactics == ("privilege-escalation",)

    def test_from_config_raises_on_invalid_regex(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        with pytest.raises(ValueError, match="Invalid regex"):
            AttackMapper.from_config(
                [{"pattern": "[invalid", "tactics": ["x"], "techniques": ["T1"]}]
            )

    def test_case_insensitive_matching(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper, AttackMapping

        mapper = AttackMapper(
            [
                AttackMapping.from_raw(
                    pattern="SSH.*FAILED",
                    tactics=["credential-access"],
                    techniques=["T1110"],
                )
            ]
        )
        tactics, _ = mapper.lookup("ssh connection failed")
        assert tactics == ("credential-access",)


class TestLoadDefaults:
    def test_load_defaults_returns_non_empty_mapper(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        assert len(mapper) >= 5

    def test_default_matches_ssh_brute_force(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, techniques = mapper.lookup(
            "error: maximum authentication attempts exceeded for user admin from 10.0.0.1"
        )
        assert "credential-access" in tactics
        assert "T1110" in techniques

    def test_default_matches_sudo_failure(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, _ = mapper.lookup("sudo: 3 incorrect password attempts")
        assert "privilege-escalation" in tactics

    def test_default_matches_segfault(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, _ = mapper.lookup("segfault at 0x0000 in /usr/bin/app")
        assert "execution" in tactics

    def test_default_no_match_normal_log(self) -> None:
        from seerflow.detection.attack_mapping import AttackMapper

        mapper = AttackMapper.load_defaults()
        tactics, techniques = mapper.lookup("INFO: server started on port 8080")
        assert tactics == ()
        assert techniques == ()


class TestMlAlertMitreParams:
    def test_create_ml_alert_with_mitre(self) -> None:
        import uuid

        from seerflow.detection.ensemble import DetectionResult
        from seerflow.models.alert import create_ml_alert
        from seerflow.models.event import SeerflowEvent, SeverityLevel

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="error: maximum authentication attempts exceeded for admin",
            template_id=42,
            template_str="error: maximum authentication attempts exceeded for <*>",
            severity_id=SeverityLevel.WARNING,
            source_type="syslog",
        )
        result = DetectionResult(
            score=0.95,
            upper_threshold=0.80,
            lower_threshold=0.10,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        alert = create_ml_alert(
            event,
            result,
            mitre_tactics=("credential-access",),
            mitre_techniques=("T1110",),
        )
        assert alert.mitre_tactics == ("credential-access",)
        assert alert.mitre_techniques == ("T1110",)

    def test_create_ml_alert_default_empty_mitre(self) -> None:
        import uuid

        from seerflow.detection.ensemble import DetectionResult
        from seerflow.models.alert import create_ml_alert
        from seerflow.models.event import SeerflowEvent, SeverityLevel

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="normal log",
            template_id=1,
            severity_id=SeverityLevel.INFORMATIONAL,
            source_type="test",
        )
        result = DetectionResult(
            score=0.5,
            upper_threshold=0.8,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="test",
        )
        alert = create_ml_alert(event, result)
        assert alert.mitre_tactics == ()
        assert alert.mitre_techniques == ()

    def test_create_ml_alerts_passes_mitre_params(self) -> None:
        import uuid

        from seerflow.detection.ensemble import DetectionResult
        from seerflow.models.alert import create_ml_alerts
        from seerflow.models.event import SeerflowEvent, SeverityLevel

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="error: authentication failed for admin",
            template_id=42,
            severity_id=SeverityLevel.WARNING,
            source_type="syslog",
            related_ips=("10.0.0.1",),
        )
        result = DetectionResult(
            score=0.9,
            upper_threshold=0.8,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ip:10.0.0.1"))
        alerts = create_ml_alerts(
            event,
            result,
            [("ip", entity_uuid)],
            mitre_tactics=("credential-access",),
            mitre_techniques=("T1110",),
        )
        assert len(alerts) == 1
        assert alerts[0].mitre_tactics == ("credential-access",)
        assert alerts[0].mitre_techniques == ("T1110",)

    def test_create_ml_alerts_fallback_passes_mitre_params(self) -> None:
        import uuid

        from seerflow.detection.ensemble import DetectionResult
        from seerflow.models.alert import create_ml_alerts
        from seerflow.models.event import SeerflowEvent, SeverityLevel

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="error: authentication failed",
            template_id=42,
            severity_id=SeverityLevel.WARNING,
            source_type="syslog",
        )
        result = DetectionResult(
            score=0.9,
            upper_threshold=0.8,
            lower_threshold=0.1,
            is_anomaly=True,
            anomaly_direction="upper",
            source_type="syslog",
        )
        alerts = create_ml_alerts(
            event,
            result,
            [],
            mitre_tactics=("initial-access",),
            mitre_techniques=("T1078",),
        )
        assert len(alerts) == 1
        assert alerts[0].mitre_tactics == ("initial-access",)
        assert alerts[0].mitre_techniques == ("T1078",)
