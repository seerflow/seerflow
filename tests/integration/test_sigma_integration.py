"""Integration tests for Sigma engine with real SeerflowEvents."""

from __future__ import annotations

from pathlib import Path

from seerflow.sigma.engine import SigmaEngine
from tests.helpers import make_event

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sigma_rules"


class TestSigmaIntegration:
    def test_full_pipeline_whoami_detection(self) -> None:
        """End-to-end: load rule -> create event -> evaluate -> get alert."""
        engine = SigmaEngine()
        engine.load_rules([FIXTURES / "test_whoami.yml"])

        event = make_event(
            message="uid=0(root) gid=0(root) groups=0(root) -- whoami output",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.alert_type == "sigma"
        assert alert.rule_name == "Whoami Execution"
        assert "discovery" in alert.mitre_tactics
        assert "t1033" in alert.mitre_techniques

    def test_multiple_rules_one_event(self) -> None:
        """An event can match multiple rules if they share logsource."""
        engine = SigmaEngine()
        engine.load_rules(list(FIXTURES.glob("*.yml")))

        event = make_event(
            message="Failed password for root -- whoami",
            log_source_category="process_creation",
            log_source_product="linux",
        )
        alerts = engine.evaluate(event)
        assert len(alerts) >= 1  # at least whoami rule matches

    def test_no_rules_no_crash(self) -> None:
        """Engine with no rules produces no alerts and no errors."""
        engine = SigmaEngine()
        event = make_event(message="test")
        alerts = engine.evaluate(event)
        assert alerts == []
