"""Tests for the SigmaEngine orchestrator."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from seerflow.sigma.engine import SigmaEngine
from tests.helpers import make_event

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sigma_rules"


class TestSigmaEngineLoad:
    def test_load_rules_from_files(self) -> None:
        engine = SigmaEngine()
        engine.load_rules([FIXTURES / "test_whoami.yml", FIXTURES / "test_ssh_brute.yml"])
        assert engine.rule_count == 2

    def test_load_rules_indexes_by_logsource(self) -> None:
        engine = SigmaEngine()
        engine.load_rules([FIXTURES / "test_whoami.yml", FIXTURES / "test_ssh_brute.yml"])
        summary = engine.logsource_summary
        assert ("process_creation", "linux", "") in summary
        assert ("authentication", "linux", "sshd") in summary

    def test_load_invalid_rule_skips_with_warning(self, tmp_path: Path) -> None:
        bad_rule = tmp_path / "bad.yml"
        bad_rule.write_text("not: valid: sigma: rule:")
        engine = SigmaEngine()
        engine.load_rules([bad_rule])
        assert engine.rule_count == 0

    def test_load_empty_list(self) -> None:
        engine = SigmaEngine()
        engine.load_rules([])
        assert engine.rule_count == 0


class TestSigmaEngineEvaluate:
    @pytest.fixture()
    def engine(self) -> SigmaEngine:
        e = SigmaEngine()
        e.load_rules([FIXTURES / "test_whoami.yml", FIXTURES / "test_ssh_brute.yml"])
        return e

    def test_matching_event_produces_alert(self, engine: SigmaEngine) -> None:
        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "Whoami Execution"
        assert alerts[0].alert_type == "sigma"

    def test_non_matching_event_produces_no_alert(self, engine: SigmaEngine) -> None:
        event = make_event(
            message="ls -la",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 0

    def test_logsource_dispatch_filters_rules(self, engine: SigmaEngine) -> None:
        event = make_event(
            message="bash -c whoami",
            log_source_category="authentication",
            log_source_product="linux",
            log_source_service="sshd",
        )
        alerts = engine.evaluate(event)
        # whoami rule is process_creation, not authentication — should not match
        assert len(alerts) == 0

    def test_alert_has_mitre_tags(self, engine: SigmaEngine) -> None:
        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert "discovery" in alerts[0].mitre_tactics
        assert "t1033" in alerts[0].mitre_techniques

    def test_ssh_brute_force_match(self, engine: SigmaEngine) -> None:
        event = make_event(
            message="Failed password for root from 10.0.0.1 port 22",
            log_source_category="authentication",
            log_source_product="linux",
            log_source_service="sshd",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert alerts[0].rule_name == "SSH Brute Force Attempt"
        assert alerts[0].severity_id.value >= 4  # HIGH or above

    def test_alert_id_is_uuid5(self, engine: SigmaEngine) -> None:
        """Alert IDs should be deterministic UUID5 strings."""

        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        parsed = uuid.UUID(alerts[0].alert_id)
        assert parsed.version == 5

    def test_alert_contains_contributing_event(self, engine: SigmaEngine) -> None:
        """Alert should reference the triggering event."""
        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert event.event_id in alerts[0].contributing_events

    def test_alert_entity_from_event(self, engine: SigmaEngine) -> None:
        """Alert entity fields come from the event's entity_refs and related_* fields."""
        event = make_event(
            message="bash -c whoami",
            log_source_category="process_creation",
            log_source_product="linux",
            entity_refs=("10.0.0.1", "admin"),
            related_ips=("10.0.0.1",),
            related_users=("admin",),
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        assert alerts[0].entity_uuid == event.entity_refs[0]
        assert alerts[0].entity_value == event.related_ips[0]


class TestEventToDict:
    """S-149: _event_to_dict includes all SeerflowEvent fields dynamically."""

    def test_includes_all_struct_fields(self) -> None:
        import msgspec.structs

        from seerflow.sigma.engine import _event_to_dict
        from tests.helpers import make_event

        event = make_event(message="test", related_ips=("10.0.0.1",))
        d = _event_to_dict(event)

        expected_fields = {f.name for f in msgspec.structs.fields(event)} - {"body", "raw_event"}
        assert set(d.keys()) == expected_fields

    def test_excludes_body_and_raw_event(self) -> None:
        from seerflow.sigma.engine import _event_to_dict
        from tests.helpers import make_event

        event = make_event()
        d = _event_to_dict(event)
        assert "body" not in d
        assert "raw_event" not in d

    def test_severity_id_converted_to_value(self) -> None:
        from seerflow.sigma.engine import _event_to_dict
        from tests.helpers import make_event

        event = make_event()
        d = _event_to_dict(event)
        assert isinstance(d["severity_id"], int)

    def test_related_domains_available(self) -> None:
        import uuid

        from seerflow.models.event import SeerflowEvent
        from seerflow.sigma.engine import _event_to_dict

        event = SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000,
            observed_ns=1_700_000_000_000_000_000,
            message="test",
            related_domains=("evil.com",),
        )
        d = _event_to_dict(event)
        assert d["related_domains"] == ("evil.com",)


class TestMakeEventExpansion:
    """S-149: make_event accepts all commonly-used SeerflowEvent fields."""

    def test_new_fields_accepted(self) -> None:
        from tests.helpers import make_event

        event = make_event(
            template_str="Failed login for <*>",
            related_domains=("evil.com",),
            related_files=("/etc/passwd",),
            related_processes=("sshd",),
            event_kind="alert",
            event_category="authentication",
            event_type="start",
            event_action="logon-failed",
            event_outcome="failure",
        )
        assert event.template_str == "Failed login for <*>"
        assert event.related_domains == ("evil.com",)
        assert event.related_files == ("/etc/passwd",)
        assert event.related_processes == ("sshd",)
        assert event.event_kind == "alert"
        assert event.event_category == "authentication"
        assert event.event_type == "start"
        assert event.event_action == "logon-failed"
        assert event.event_outcome == "failure"
