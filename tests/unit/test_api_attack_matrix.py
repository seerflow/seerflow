"""Unit tests for src/seerflow/api/attack.py pure matrix functions."""

from __future__ import annotations

from datetime import UTC, datetime

from seerflow.api.attack import (
    build_matrix,
    collect_alert_cells,
    collect_correlation_cells,
    collect_sigma_cells,
)
from seerflow.models.alert import Alert, CorrelationRule, SourceCondition
from seerflow.models.event import SeverityLevel
from seerflow.sigma.attack import TACTICS


class _StubSigmaEngine:
    def __init__(self, rules: list[object]) -> None:
        self._rules = rules

    def iter_compiled_rules(self) -> object:
        yield from self._rules


class _StubCompiled:
    def __init__(
        self,
        tactics: tuple[str, ...],
        techniques: tuple[str, ...],
    ) -> None:
        self.attack_tactics = tactics
        self.attack_techniques = techniques


def _alert(
    tactics: tuple[str, ...],
    techniques: tuple[str, ...],
    *,
    alert_id: str = "a",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type="sigma",
        timestamp_ns=0,
        severity_id=SeverityLevel.WARNING,
        rule_name="test",
        description="",
        entity_uuid="e",
        entity_value="v",
        entity_type="ip",
        contributing_events=(),
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


def _corr(
    tactics: tuple[str, ...],
    techniques: tuple[str, ...],
) -> CorrelationRule:
    return CorrelationRule(
        name="c",
        entity_type="ip",
        window_seconds=60,
        sources=(SourceCondition(source_type="syslog", conditions={}),),
        min_sources=1,
        alert_severity=SeverityLevel.WARNING,
        mitre_tactics=tactics,
        mitre_techniques=techniques,
    )


class TestCollectSigmaCells:
    def test_none_engine_returns_empty(self) -> None:
        assert collect_sigma_cells(None) == {}

    def test_counts_pairs(self) -> None:
        engine = _StubSigmaEngine(
            [
                _StubCompiled(("discovery",), ("t1033", "t1087")),
                _StubCompiled(("discovery",), ("t1033",)),
            ]
        )
        counts = collect_sigma_cells(engine)  # type: ignore[arg-type]
        assert counts[("discovery", "T1033")] == 2
        assert counts[("discovery", "T1087")] == 1

    def test_drops_orphans(self) -> None:
        engine = _StubSigmaEngine(
            [
                _StubCompiled((), ("t1033",)),
                _StubCompiled(("discovery",), ()),
            ]
        )
        assert collect_sigma_cells(engine) == {}  # type: ignore[arg-type]

    def test_skips_empty_string_tactic_and_technique_entries(self) -> None:
        engine = _StubSigmaEngine(
            [
                _StubCompiled(("",), ("t1033",)),
                _StubCompiled(("discovery",), ("",)),
                _StubCompiled(("discovery",), ("t1033",)),
            ]
        )
        counts = collect_sigma_cells(engine)  # type: ignore[arg-type]
        assert counts == {("discovery", "T1033"): 1}


class TestCollectCorrelationCells:
    def test_normalizes_technique_case(self) -> None:
        rules = [_corr(("lateral_movement",), ("T1021",))]
        counts = collect_correlation_cells(rules)
        assert counts == {("lateral_movement", "T1021"): 1}

    def test_empty_sequence_returns_empty(self) -> None:
        assert collect_correlation_cells([]) == {}

    def test_drops_orphan_correlation_rules(self) -> None:
        rules = [_corr((), ("T1021",)), _corr(("lateral_movement",), ())]
        assert collect_correlation_cells(rules) == {}

    def test_skips_empty_string_entries(self) -> None:
        rules = [
            _corr(("",), ("T1021",)),
            _corr(("lateral_movement",), ("",)),
            _corr(("lateral_movement",), ("T1021",)),
        ]
        counts = collect_correlation_cells(rules)
        assert counts == {("lateral_movement", "T1021"): 1}


class TestCollectAlertCells:
    def test_normalizes_technique_case(self) -> None:
        alerts = [
            _alert(("discovery",), ("t1033",), alert_id="a1"),
            _alert(("discovery",), ("T1033",), alert_id="a2"),
        ]
        counts = collect_alert_cells(alerts)
        assert counts == {("discovery", "T1033"): 2}

    def test_drops_orphans(self) -> None:
        alerts = [_alert((), ("t1033",), alert_id="a1")]
        assert collect_alert_cells(alerts) == {}

    def test_skips_empty_string_entries(self) -> None:
        alerts = [
            _alert(("",), ("t1033",), alert_id="a1"),
            _alert(("discovery",), ("",), alert_id="a2"),
            _alert(("discovery",), ("t1033",), alert_id="a3"),
        ]
        counts = collect_alert_cells(alerts)
        assert counts == {("discovery", "T1033"): 1}


class TestBuildMatrix:
    _since = datetime(2026, 3, 12, tzinfo=UTC)
    _until = datetime(2026, 4, 11, tzinfo=UTC)

    def test_includes_all_known_tactics(self) -> None:
        resp = build_matrix({}, {}, window_since=self._since, window_until=self._until)
        assert [t.tactic for t in resp.tactics] == list(TACTICS.keys())
        for tactic in resp.tactics:
            assert tactic.techniques == []

    def test_fills_cell_flags_and_summary(self) -> None:
        rule_counts = {("discovery", "T1033"): 2, ("execution", "T1059"): 1}
        alert_counts = {("discovery", "T1033"): 5}
        resp = build_matrix(
            rule_counts, alert_counts, window_since=self._since, window_until=self._until
        )
        discovery = next(t for t in resp.tactics if t.tactic == "discovery")
        assert discovery.tactic_display_name == "Discovery (TA0007)"
        t1033 = discovery.techniques[0]
        assert t1033.rule_count == 2
        assert t1033.alert_count == 5
        assert t1033.covered is True
        assert t1033.detected is True

        execution = next(t for t in resp.tactics if t.tactic == "execution")
        t1059 = execution.techniques[0]
        assert t1059.covered is True
        assert t1059.detected is False

        assert resp.summary.total_techniques_covered == 2
        assert resp.summary.total_techniques_detected == 1
        assert resp.summary.total_rules_with_attack_tags == 3
        assert resp.summary.total_alerts_matched == 5

    def test_unknown_tactics_appended(self) -> None:
        rule_counts = {("custom_tactic", "T9999"): 1}
        resp = build_matrix(rule_counts, {}, window_since=self._since, window_until=self._until)
        known_count = len(TACTICS)
        assert len(resp.tactics) == known_count + 1
        assert resp.tactics[-1].tactic == "custom_tactic"
        assert resp.tactics[-1].tactic_display_name == "custom_tactic"
        assert resp.tactics[-1].techniques[0].technique == "T9999"

    def test_techniques_sorted_within_tactic(self) -> None:
        rule_counts = {
            ("discovery", "T1087"): 1,
            ("discovery", "T1033"): 1,
            ("discovery", "T1059"): 1,
        }
        resp = build_matrix(rule_counts, {}, window_since=self._since, window_until=self._until)
        discovery = next(t for t in resp.tactics if t.tactic == "discovery")
        techs = [c.technique for c in discovery.techniques]
        assert techs == sorted(techs)

    def test_window_fields_from_datetimes(self) -> None:
        resp = build_matrix({}, {}, window_since=self._since, window_until=self._until)
        assert resp.window_since.startswith("2026-03-12")
        assert resp.window_until.startswith("2026-04-11")
