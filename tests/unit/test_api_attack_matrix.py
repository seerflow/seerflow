"""Unit tests for src/seerflow/api/attack.py pure matrix functions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from seerflow.api.attack import (
    CellData,
    _collect_tag_pairs,
    build_matrix,
    collect_alert_cells,
    collect_correlation_cells,
    collect_sigma_cells,
    merge_rule_data,
)
from seerflow.models.alert import Alert, CorrelationRule, SourceCondition
from seerflow.models.event import SeverityLevel
from seerflow.sigma.attack import TACTICS

if TYPE_CHECKING:
    from collections.abc import Iterator


class _StubSigmaEngine:
    def __init__(self, rules: list[_StubCompiled]) -> None:
        self._rules = rules

    def iter_compiled_rules(self) -> Iterator[_StubCompiled]:
        yield from self._rules


class _StubCompiled:
    def __init__(
        self,
        tactics: tuple[str, ...],
        techniques: tuple[str, ...],
        rule_name: str = "test",
    ) -> None:
        self.attack_tactics = tactics
        self.attack_techniques = techniques
        self.rule_name = rule_name


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
    *,
    name: str = "brute_force_lateral",
) -> CorrelationRule:
    return CorrelationRule(
        name=name,
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
        counts = collect_sigma_cells(engine)
        assert counts[("discovery", "T1033")].count == 2
        assert counts[("discovery", "T1087")].count == 1

    def test_drops_orphans(self) -> None:
        engine = _StubSigmaEngine(
            [
                _StubCompiled((), ("t1033",)),
                _StubCompiled(("discovery",), ()),
            ]
        )
        assert collect_sigma_cells(engine) == {}

    def test_skips_empty_string_tactic_and_technique_entries(self) -> None:
        engine = _StubSigmaEngine(
            [
                _StubCompiled(("",), ("t1033",)),
                _StubCompiled(("discovery",), ("",)),
                _StubCompiled(("discovery",), ("t1033",)),
            ]
        )
        counts = collect_sigma_cells(engine)
        assert list(counts.keys()) == [("discovery", "T1033")]
        assert counts[("discovery", "T1033")].count == 1


def test_collect_sigma_cells_returns_cell_data_with_rule_names() -> None:
    rules = [
        _StubCompiled(("persistence",), ("T1053",), rule_name="sched_task_cron"),
        _StubCompiled(("persistence",), ("T1053",), rule_name="crontab_mod"),
    ]
    engine = _StubSigmaEngine(rules)
    result = collect_sigma_cells(engine)
    cell = result[("persistence", "T1053")]
    assert cell.count == 2
    assert cell.rule_names == ("sched_task_cron", "crontab_mod")


def test_collect_sigma_cells_none_engine_returns_empty() -> None:
    result = collect_sigma_cells(None)
    assert result == {}


class TestCollectCorrelationCells:
    def test_normalizes_technique_case(self) -> None:
        rules = [_corr(("lateral_movement",), ("T1021",))]
        counts = collect_correlation_cells(rules)
        assert counts[("lateral_movement", "T1021")].count == 1

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
        assert list(counts.keys()) == [("lateral_movement", "T1021")]
        assert counts[("lateral_movement", "T1021")].count == 1


class TestCollectAlertCells:
    def test_normalizes_technique_case(self) -> None:
        alerts = [
            _alert(("discovery",), ("t1033",), alert_id="a1"),
            _alert(("discovery",), ("T1033",), alert_id="a2"),
        ]
        counts = collect_alert_cells(alerts)
        assert counts[("discovery", "T1033")].count == 2

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
        assert list(counts.keys()) == [("discovery", "T1033")]
        assert counts[("discovery", "T1033")].count == 1


class TestBuildMatrix:
    _since = datetime(2026, 3, 12, tzinfo=UTC)
    _until = datetime(2026, 4, 11, tzinfo=UTC)

    def test_includes_all_known_tactics(self) -> None:
        resp = build_matrix({}, {}, window_since=self._since, window_until=self._until)
        assert [t.tactic for t in resp.tactics] == list(TACTICS.keys())
        for tactic in resp.tactics:
            assert tactic.techniques == []

    def test_fills_cell_flags_and_summary(self) -> None:
        rule_data = {
            ("discovery", "T1033"): CellData(count=2),
            ("execution", "T1059"): CellData(count=1),
        }
        alert_data = {("discovery", "T1033"): CellData(count=5)}
        resp = build_matrix(
            rule_data, alert_data, window_since=self._since, window_until=self._until
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
        rule_data = {("custom_tactic", "T9999"): CellData(count=1)}
        resp = build_matrix(rule_data, {}, window_since=self._since, window_until=self._until)
        known_count = len(TACTICS)
        assert len(resp.tactics) == known_count + 1
        assert resp.tactics[-1].tactic == "custom_tactic"
        assert resp.tactics[-1].tactic_display_name == "custom_tactic"
        assert resp.tactics[-1].techniques[0].technique == "T9999"

    def test_techniques_sorted_within_tactic(self) -> None:
        rule_data = {
            ("discovery", "T1087"): CellData(count=1),
            ("discovery", "T1033"): CellData(count=1),
            ("discovery", "T1053"): CellData(count=1),
            ("discovery", "T1053.001"): CellData(count=1),
            ("discovery", "T1059"): CellData(count=1),
        }
        resp = build_matrix(rule_data, {}, window_since=self._since, window_until=self._until)
        discovery = next(t for t in resp.tactics if t.tactic == "discovery")
        techs = [c.technique for c in discovery.techniques]
        # Lexicographic ordering — T1033 < T1053 < T1053.001 < T1059 < T1087.
        assert techs == ["T1033", "T1053", "T1053.001", "T1059", "T1087"]

    def test_window_fields_from_datetimes(self) -> None:
        resp = build_matrix({}, {}, window_since=self._since, window_until=self._until)
        assert resp.window_since.startswith("2026-03-12")
        assert resp.window_until.startswith("2026-04-11")


def test_build_matrix_populates_rule_names() -> None:
    rule_data = {
        ("persistence", "T1053"): CellData(count=2, rule_names=("sched_task", "crontab")),
    }
    alert_data = {
        ("persistence", "T1053"): CellData(count=1),
    }
    now = datetime.now(UTC)
    resp = build_matrix(rule_data, alert_data, window_since=now, window_until=now)
    tactic = next(t for t in resp.tactics if t.tactic == "persistence")
    cell = next(c for c in tactic.techniques if c.technique == "T1053")
    assert cell.rule_names == ["sched_task", "crontab"]
    assert cell.rule_count == 2
    assert cell.alert_count == 1


# ---------------------------------------------------------------------------
# New Task 2 tests: CellData-aware collectors and merge_rule_data
# ---------------------------------------------------------------------------


def test_collect_correlation_cells_returns_cell_data_with_names() -> None:
    rules = [
        _corr(("lateral_movement",), ("T1021",)),
    ]
    result = collect_correlation_cells(rules)
    cell = result[("lateral_movement", "T1021")]
    assert cell.count == 1
    assert cell.rule_names == ("brute_force_lateral",)


def test_collect_alert_cells_returns_cell_data() -> None:
    alerts = [_alert(("persistence",), ("T1053",))]
    result = collect_alert_cells(alerts)
    cell = result[("persistence", "T1053")]
    assert cell.count == 1
    assert cell.rule_names == ()  # alerts don't carry rule_names into cell


def test_merge_rule_data_combines_counts_and_names() -> None:
    a: dict[tuple[str, str], CellData] = {
        ("persistence", "T1053"): CellData(count=2, rule_names=("r1", "r2"))
    }
    b: dict[tuple[str, str], CellData] = {
        ("persistence", "T1053"): CellData(count=1, rule_names=("r3",))
    }
    merged = merge_rule_data(a, b)
    cell = merged[("persistence", "T1053")]
    assert cell.count == 3
    assert cell.rule_names == ("r1", "r2", "r3")


class TestCollectTagPairsRollup:
    def test_subtechnique_rolls_into_parent(self) -> None:
        cells: dict[tuple[str, str], CellData] = {}
        _collect_tag_pairs(("persistence",), ("T1053.005",), cells, "rule_a")
        assert cells == {("persistence", "T1053"): CellData(count=1, rule_names=("rule_a",))}

    def test_parent_and_sub_on_same_rule_dedups(self) -> None:
        cells: dict[tuple[str, str], CellData] = {}
        _collect_tag_pairs(("persistence",), ("T1053", "T1053.005"), cells, "rule_a")
        assert cells == {("persistence", "T1053"): CellData(count=1, rule_names=("rule_a",))}

    def test_two_subs_same_parent_same_rule_dedup(self) -> None:
        cells: dict[tuple[str, str], CellData] = {}
        _collect_tag_pairs(("persistence",), ("T1053.005", "T1053.001"), cells, "rule_a")
        assert cells == {("persistence", "T1053"): CellData(count=1, rule_names=("rule_a",))}

    def test_two_rules_same_parent_accumulate(self) -> None:
        cells: dict[tuple[str, str], CellData] = {}
        _collect_tag_pairs(("persistence",), ("T1053.005",), cells, "rule_a")
        _collect_tag_pairs(("persistence",), ("T1053.001",), cells, "rule_b")
        assert cells[("persistence", "T1053")].count == 2
        assert set(cells[("persistence", "T1053")].rule_names) == {"rule_a", "rule_b"}

    def test_lowercase_subtechnique_normalized(self) -> None:
        cells: dict[tuple[str, str], CellData] = {}
        _collect_tag_pairs(("persistence",), ("t1053.005",), cells, "rule_a")
        assert cells == {("persistence", "T1053"): CellData(count=1, rule_names=("rule_a",))}
