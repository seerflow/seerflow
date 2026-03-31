"""Integration tests: CorrelationEngine fires built-in rules against synthetic events."""

from __future__ import annotations

import time
import uuid

from seerflow.correlation.bundled import get_bundled_rule_dir
from seerflow.correlation.engine import CorrelationEngine
from seerflow.correlation.rule_loader import load_correlation_rules
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.models.event import SeerflowEvent, SeverityLevel


def _make_event(
    *,
    message: str = "test event",
    source_type: str = "syslog",
    related_ips: tuple[str, ...] = (),
    related_users: tuple[str, ...] = (),
    related_hosts: tuple[str, ...] = (),
    timestamp_ns: int | None = None,
) -> SeerflowEvent:
    now_ns = timestamp_ns if timestamp_ns is not None else time.time_ns()
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=now_ns,
        observed_ns=now_ns + 1_000_000,
        severity_id=SeverityLevel.INFORMATIONAL,
        message=message,
        source_type=source_type,
        related_ips=related_ips,
        related_users=related_users,
        related_hosts=related_hosts,
    )


def _load_builtin_rules() -> list:
    return load_correlation_rules([str(get_bundled_rule_dir())])


class TestBruteForceRuleFires:
    def test_brute_force_fires_after_failures_then_success(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=700_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "user:alice"))
        base_ns = time.time_ns()

        # 5 failed login events
        for i in range(5):
            evt = _make_event(
                message=f"Failed password for alice from 10.0.0.1 attempt {i}",
                related_users=("alice",),
                timestamp_ns=base_ns + i * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        # 1 successful login
        trigger = _make_event(
            message="Accepted password for alice from 10.0.0.2",
            related_users=("alice",),
            timestamp_ns=base_ns + 6_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        rule_names = {a.rule_name for a in alerts}
        assert "brute-force-lateral-movement" in rule_names


class TestCredentialStuffingRuleFires:
    def test_credential_stuffing_fires_on_many_failures(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=400_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ip:10.0.0.99"))
        base_ns = time.time_ns()

        # 10 failed logins from same IP
        for i in range(10):
            evt = _make_event(
                message=f"authentication failure for user{i} from 10.0.0.99",
                related_ips=("10.0.0.99",),
                timestamp_ns=base_ns + i * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        trigger = _make_event(
            message="authentication failure for user10 from 10.0.0.99",
            related_ips=("10.0.0.99",),
            timestamp_ns=base_ns + 11_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        rule_names = {a.rule_name for a in alerts}
        assert "credential-stuffing" in rule_names


class TestPrivilegeEscalationRuleFires:
    def test_privilege_escalation_fires_on_sudo_then_shadow(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=700_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "user:mallory"))
        base_ns = time.time_ns()

        # Privilege elevation
        evt1 = _make_event(
            message="sudo: mallory : command=/bin/bash",
            related_users=("mallory",),
            timestamp_ns=base_ns,
        )
        window.add_event(entity_uuid, evt1)

        # Sensitive file access
        trigger = _make_event(
            message="mallory accessed /etc/shadow",
            related_users=("mallory",),
            timestamp_ns=base_ns + 5_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        rule_names = {a.rule_name for a in alerts}
        assert "privilege-escalation-chain" in rule_names


class TestDataExfiltrationRuleFires:
    def test_exfiltration_fires_on_transfer_and_file_access(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=1_000_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ip:192.168.1.50"))
        base_ns = time.time_ns()

        # 3 outbound transfer events
        for i in range(3):
            evt = _make_event(
                message="large transfer outbound bytes sent 1500000 to external",
                related_ips=("192.168.1.50",),
                timestamp_ns=base_ns + i * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        # 2 file access events
        for i in range(2):
            evt = _make_event(
                message="scp file access to remote host completed",
                related_ips=("192.168.1.50",),
                timestamp_ns=base_ns + (3 + i) * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        trigger = _make_event(
            message="curl upload completed to external server",
            related_ips=("192.168.1.50",),
            timestamp_ns=base_ns + 6_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        rule_names = {a.rule_name for a in alerts}
        assert "data-exfiltration" in rule_names


class TestC2BeaconingRuleFires:
    def test_c2_beaconing_fires_on_repeated_callbacks(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=2_000_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ip:10.0.0.5"))
        base_ns = time.time_ns()

        # 5 beacon-like connections
        for i in range(5):
            evt = _make_event(
                message=f"outbound http callback to established 203.0.113.{i}",
                related_ips=("10.0.0.5",),
                timestamp_ns=base_ns + i * 60_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        trigger = _make_event(
            message="outbound http beacon to established 203.0.113.99",
            related_ips=("10.0.0.5",),
            timestamp_ns=base_ns + 6 * 60_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        rule_names = {a.rule_name for a in alerts}
        assert "c2-beaconing" in rule_names


class TestNegativeCases:
    def test_benign_events_do_not_fire_any_rule(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=2_000_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ip:10.0.0.1"))
        base_ns = time.time_ns()

        # Normal log traffic
        for i in range(5):
            evt = _make_event(
                message=f"INFO application started on port 8080 request {i}",
                related_ips=("10.0.0.1",),
                timestamp_ns=base_ns + i * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        trigger = _make_event(
            message="INFO health check passed 200 OK",
            related_ips=("10.0.0.1",),
            timestamp_ns=base_ns + 6_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        assert alerts == []

    def test_insufficient_events_do_not_fire(self) -> None:
        rules = _load_builtin_rules()
        window = EntityWindowBuffer(window_ns=700_000_000_000, max_events=1000)
        engine = CorrelationEngine(rules=rules, window=window)

        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "user:bob"))
        base_ns = time.time_ns()

        # Only 2 auth failures (brute force needs 5)
        for i in range(2):
            evt = _make_event(
                message=f"Failed password for bob attempt {i}",
                related_users=("bob",),
                timestamp_ns=base_ns + i * 1_000_000_000,
            )
            window.add_event(entity_uuid, evt)

        trigger = _make_event(
            message="Accepted password for bob",
            related_users=("bob",),
            timestamp_ns=base_ns + 3_000_000_000,
        )
        window.add_event(entity_uuid, trigger)

        alerts = engine.evaluate(trigger, (entity_uuid,))
        # Brute force should NOT fire (only 2 failures, needs 5)
        brute_force = [a for a in alerts if a.rule_name == "brute-force-lateral-movement"]
        assert brute_force == []
