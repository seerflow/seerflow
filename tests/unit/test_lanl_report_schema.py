"""Unit tests for seerflow.lanl.report.schema (S-358 slice 1).

TDD RED phase — these tests must FAIL before the implementation exists.
"""

from __future__ import annotations

import types

import msgspec
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_validation_result(**overrides: object) -> types.SimpleNamespace:
    """Return a minimal fake ValidationResult-like namespace."""
    defaults: dict[str, object] = {
        "precision": 0.8,
        "recall": 0.75,
        "f1_score": 0.774,
        "auc": 0.91,
        "false_positive_rate": 0.05,
        "true_positives": 3,
        "false_positives": 1,
        "false_negatives": 1,
        "total_alerts": 4,
        "patterns_detected": frozenset(["brute-force-lateral-movement", "c2-beaconing"]),
        "attack_scenarios": (),
        "missed_attributions": (),
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Literal aliases + result Protocol (S-359)
# ---------------------------------------------------------------------------


def test_literal_aliases_exported() -> None:
    from typing import get_args

    from seerflow.lanl.report.schema import BaselineKind, Comparison, Verdict

    assert frozenset(get_args(BaselineKind)) == {"project_target", "published"}
    assert frozenset(get_args(Comparison)) == {"lt", "lte", "gt", "gte"}
    assert frozenset(get_args(Verdict)) == {"pass", "below", "above", "n/a"}


def test_validation_result_protocol_accepts_namespace() -> None:
    """A SimpleNamespace ValidationResult fake structurally satisfies the Protocol."""
    from seerflow.lanl.report.schema import ValidationResultLike

    fake: ValidationResultLike = _make_fake_validation_result()  # type: ignore[assignment]
    assert fake.precision == 0.8


# ---------------------------------------------------------------------------
# HostInfo
# ---------------------------------------------------------------------------


class TestHostInfo:
    def test_construct_all_fields(self) -> None:
        from seerflow.lanl.report.schema import HostInfo

        h = HostInfo(
            cpu_model="Intel Core i9",
            physical_cores=8,
            logical_cores=16,
            ram_gb=32.0,
            platform="Linux-6.1-x86_64",
        )
        assert h.cpu_model == "Intel Core i9"
        assert h.physical_cores == 8
        assert h.logical_cores == 16
        assert h.ram_gb == 32.0
        assert h.platform == "Linux-6.1-x86_64"

    def test_construct_nullable_fields(self) -> None:
        from seerflow.lanl.report.schema import HostInfo

        h = HostInfo(
            cpu_model=None,
            physical_cores=None,
            logical_cores=None,
            ram_gb=None,
            platform="Linux",
        )
        assert h.cpu_model is None
        assert h.ram_gb is None

    def test_frozen_immutable(self) -> None:
        from seerflow.lanl.report.schema import HostInfo

        h = HostInfo(
            cpu_model=None, physical_cores=None, logical_cores=None, ram_gb=None, platform="x"
        )
        with pytest.raises((TypeError, AttributeError)):
            h.platform = "changed"  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import HostInfo

        h = HostInfo(
            cpu_model="test", physical_cores=4, logical_cores=8, ram_gb=16.0, platform="Linux"
        )
        encoded = msgspec.json.encode(h)
        decoded = msgspec.json.decode(encoded, type=HostInfo)
        assert decoded == h


# ---------------------------------------------------------------------------
# RunTelemetry
# ---------------------------------------------------------------------------


class TestRunTelemetry:
    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import RunTelemetry

        t = RunTelemetry(
            wall_s=12.5,
            events_processed=50_000,
            throughput_eps=4000.0,
            mean_latency_s=0.00025,
            peak_rss_mb=128.5,
        )
        assert t.wall_s == 12.5
        assert t.events_processed == 50_000
        assert t.throughput_eps == 4000.0
        assert t.mean_latency_s == 0.00025
        assert t.peak_rss_mb == 128.5

    def test_peak_rss_nullable(self) -> None:
        from seerflow.lanl.report.schema import RunTelemetry

        t = RunTelemetry(
            wall_s=1.0,
            events_processed=100,
            throughput_eps=100.0,
            mean_latency_s=0.01,
            peak_rss_mb=None,
        )
        assert t.peak_rss_mb is None

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import RunTelemetry

        t = RunTelemetry(
            wall_s=1.0,
            events_processed=1,
            throughput_eps=1.0,
            mean_latency_s=0.0,
            peak_rss_mb=None,
        )
        with pytest.raises((TypeError, AttributeError)):
            t.wall_s = 99.0  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import RunTelemetry

        t = RunTelemetry(
            wall_s=5.0,
            events_processed=200,
            throughput_eps=40.0,
            mean_latency_s=0.025,
            peak_rss_mb=64.0,
        )
        encoded = msgspec.json.encode(t)
        decoded = msgspec.json.decode(encoded, type=RunTelemetry)
        assert decoded == t


# ---------------------------------------------------------------------------
# ScenarioSummary
# ---------------------------------------------------------------------------


class TestScenarioSummary:
    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import ScenarioSummary

        s = ScenarioSummary(
            name="brute-force-lateral-movement",
            detected=True,
            mttd_seconds=42.5,
            missed_record_count=0,
        )
        assert s.name == "brute-force-lateral-movement"
        assert s.detected is True
        assert s.mttd_seconds == 42.5
        assert s.missed_record_count == 0

    def test_mttd_nullable(self) -> None:
        from seerflow.lanl.report.schema import ScenarioSummary

        s = ScenarioSummary(name="c2", detected=False, mttd_seconds=None, missed_record_count=2)
        assert s.mttd_seconds is None

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import ScenarioSummary

        s = ScenarioSummary(name="x", detected=False, mttd_seconds=None, missed_record_count=0)
        with pytest.raises((TypeError, AttributeError)):
            s.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AccuracySummary
# ---------------------------------------------------------------------------


class TestAccuracySummary:
    def test_construct_directly(self) -> None:
        from seerflow.lanl.report.schema import AccuracySummary

        a = AccuracySummary(
            precision=0.9,
            recall=0.8,
            f1=0.847,
            auc=0.92,
            false_positive_rate=0.05,
            true_positives=9,
            false_positives=1,
            false_negatives=2,
            total_alerts=10,
            patterns_detected=("rule-a", "rule-b"),
            scenarios=(),
            missed_attributions=(),
        )
        assert a.precision == 0.9
        assert a.f1 == 0.847
        assert a.patterns_detected == ("rule-a", "rule-b")

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import AccuracySummary

        a = AccuracySummary(
            precision=0.5,
            recall=0.5,
            f1=0.5,
            auc=0.5,
            false_positive_rate=0.1,
            true_positives=1,
            false_positives=1,
            false_negatives=1,
            total_alerts=2,
            patterns_detected=(),
            scenarios=(),
            missed_attributions=(),
        )
        with pytest.raises((TypeError, AttributeError)):
            a.precision = 0.99  # type: ignore[misc]

    def test_from_validation_result_basic_fields(self) -> None:
        from seerflow.lanl.report.schema import AccuracySummary

        fake = _make_fake_validation_result()
        summary = AccuracySummary.from_validation_result(fake)

        assert summary.precision == pytest.approx(0.8)
        assert summary.recall == pytest.approx(0.75)
        assert summary.auc == pytest.approx(0.91)
        assert summary.false_positive_rate == pytest.approx(0.05)
        assert summary.true_positives == 3
        assert summary.false_positives == 1
        assert summary.false_negatives == 1
        assert summary.total_alerts == 4

    def test_from_validation_result_f1_maps_from_f1_score(self) -> None:
        """ValidationResult uses f1_score; AccuracySummary exposes it as f1."""
        from seerflow.lanl.report.schema import AccuracySummary

        fake = _make_fake_validation_result(f1_score=0.774)
        summary = AccuracySummary.from_validation_result(fake)
        assert summary.f1 == pytest.approx(0.774)

    def test_from_validation_result_patterns_sorted_tuple(self) -> None:
        """patterns_detected becomes a sorted tuple of strings."""
        from seerflow.lanl.report.schema import AccuracySummary

        fake = _make_fake_validation_result(
            patterns_detected=frozenset(["z-rule", "a-rule", "m-rule"])
        )
        summary = AccuracySummary.from_validation_result(fake)
        assert isinstance(summary.patterns_detected, tuple)
        assert summary.patterns_detected == ("a-rule", "m-rule", "z-rule")

    def test_from_validation_result_auc_none_becomes_zero(self) -> None:
        """ValidationResult.auc can be None; AccuracySummary normalises to 0.0."""
        from seerflow.lanl.report.schema import AccuracySummary

        fake = _make_fake_validation_result(auc=None)
        summary = AccuracySummary.from_validation_result(fake)
        assert summary.auc == pytest.approx(0.0)

    def test_from_validation_result_scenarios(self) -> None:
        """attack_scenarios are mapped to ScenarioSummary tuples."""
        from seerflow.lanl.report.schema import AccuracySummary

        fake_scenario = types.SimpleNamespace(
            name="brute-force-lateral-movement",
            detected=True,
            mttd_seconds=30.0,
            missed_record_count=0,
        )
        fake = _make_fake_validation_result(attack_scenarios=(fake_scenario,))
        summary = AccuracySummary.from_validation_result(fake)

        assert len(summary.scenarios) == 1
        s = summary.scenarios[0]
        assert s.name == "brute-force-lateral-movement"
        assert s.detected is True
        assert s.mttd_seconds == pytest.approx(30.0)
        assert s.missed_record_count == 0

    def test_from_validation_result_missed_attributions(self) -> None:
        """missed_attributions tuple is preserved (as strings)."""
        from seerflow.lanl.report.schema import AccuracySummary

        fake_attr = types.SimpleNamespace(
            record_repr="r1|u1|C1|C2", scenario_name="c2", silent_family="correlation"
        )
        fake = _make_fake_validation_result(missed_attributions=(fake_attr,))
        summary = AccuracySummary.from_validation_result(fake)
        assert len(summary.missed_attributions) == 1
        assert "r1|u1|C1|C2" in summary.missed_attributions[0]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import AccuracySummary

        a = AccuracySummary(
            precision=0.9,
            recall=0.8,
            f1=0.847,
            auc=0.92,
            false_positive_rate=0.05,
            true_positives=9,
            false_positives=1,
            false_negatives=2,
            total_alerts=10,
            patterns_detected=("rule-a",),
            scenarios=(),
            missed_attributions=(),
        )
        encoded = msgspec.json.encode(a)
        decoded = msgspec.json.decode(encoded, type=AccuracySummary)
        assert decoded == a


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import Baseline

        b = Baseline(
            metric="false_positive_rate",
            kind="project_target",
            value=0.02,
            comparison="lte",
            source="PRD 2026-03-17",
            notes=None,
        )
        assert b.metric == "false_positive_rate"
        assert b.kind == "project_target"
        assert b.value == pytest.approx(0.02)
        assert b.comparison == "lte"
        assert b.notes is None

    def test_notes_optional(self) -> None:
        from seerflow.lanl.report.schema import Baseline

        b = Baseline(
            metric="auc",
            kind="published",
            value=0.9,
            comparison="gte",
            source="paper X",
            notes="see §3",
        )
        assert b.notes == "see §3"

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import Baseline

        b = Baseline(metric="auc", kind="published", value=0.9, comparison="gte", source="s")
        with pytest.raises((TypeError, AttributeError)):
            b.value = 0.5  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import Baseline

        b = Baseline(
            metric="auc", kind="project_target", value=0.0, comparison="gt", source="s", notes=None
        )
        encoded = msgspec.json.encode(b)
        decoded = msgspec.json.decode(encoded, type=Baseline)
        assert decoded == b


# ---------------------------------------------------------------------------
# ComparisonRow
# ---------------------------------------------------------------------------


class TestComparisonRow:
    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import ComparisonRow

        row = ComparisonRow(
            metric="auc",
            seerflow_value=0.91,
            baseline_name="PRD target",
            baseline_value=0.0,
            comparison="gt",
            delta=0.91,
            verdict="pass",
        )
        assert row.metric == "auc"
        assert row.verdict == "pass"

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import ComparisonRow

        row = ComparisonRow(
            metric="f1",
            seerflow_value=0.8,
            baseline_name="n",
            baseline_value=0.7,
            comparison="gt",
            delta=0.1,
            verdict="pass",
        )
        with pytest.raises((TypeError, AttributeError)):
            row.verdict = "below"  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import ComparisonRow

        row = ComparisonRow(
            metric="f1",
            seerflow_value=0.8,
            baseline_name="n",
            baseline_value=0.7,
            comparison="gt",
            delta=0.1,
            verdict="pass",
        )
        encoded = msgspec.json.encode(row)
        decoded = msgspec.json.decode(encoded, type=ComparisonRow)
        assert decoded == row


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class TestProjection:
    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import Projection

        p = Projection(
            kind="current", label="Current run", eta_seconds=None, note="synthetic subset"
        )
        assert p.kind == "current"
        assert p.eta_seconds is None

    def test_frozen(self) -> None:
        from seerflow.lanl.report.schema import Projection

        p = Projection(kind="target", label="Target", eta_seconds=3600.0, note="")
        with pytest.raises((TypeError, AttributeError)):
            p.kind = "parallel"  # type: ignore[misc]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import Projection

        p = Projection(kind="parallel", label="8-core", eta_seconds=1.5, note="est.")
        encoded = msgspec.json.encode(p)
        decoded = msgspec.json.decode(encoded, type=Projection)
        assert decoded == p


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def _make_report(self) -> object:
        from seerflow.lanl.report.schema import (
            AccuracySummary,
            ComparisonRow,
            HostInfo,
            Projection,
            Report,
            RunTelemetry,
        )

        accuracy = AccuracySummary(
            precision=0.9,
            recall=0.8,
            f1=0.847,
            auc=0.92,
            false_positive_rate=0.05,
            true_positives=9,
            false_positives=1,
            false_negatives=2,
            total_alerts=10,
            patterns_detected=(),
            scenarios=(),
            missed_attributions=(),
        )
        telemetry = RunTelemetry(
            wall_s=5.0,
            events_processed=1000,
            throughput_eps=200.0,
            mean_latency_s=0.005,
            peak_rss_mb=64.0,
        )
        host = HostInfo(
            cpu_model=None, physical_cores=None, logical_cores=None, ram_gb=None, platform="Linux"
        )
        comparison = ComparisonRow(
            metric="auc",
            seerflow_value=0.92,
            baseline_name="PRD",
            baseline_value=0.0,
            comparison="gt",
            delta=0.92,
            verdict="pass",
        )
        projection = Projection(kind="current", label="Current", eta_seconds=None, note="")
        return Report(
            accuracy=accuracy,
            telemetry=telemetry,
            host=host,
            comparisons=(comparison,),
            projections=(projection,),
            dataset_total_events=1_607_452_967,
            first_attack_events=58_655_985,
        )

    def test_construct(self) -> None:
        from seerflow.lanl.report.schema import Report

        r = self._make_report()
        assert isinstance(r, Report)
        assert r.dataset_total_events == 1_607_452_967  # type: ignore[attr-defined]
        assert r.first_attack_events == 58_655_985  # type: ignore[attr-defined]

    def test_frozen(self) -> None:
        r = self._make_report()
        with pytest.raises((TypeError, AttributeError)):
            r.dataset_total_events = 0  # type: ignore[attr-defined]

    def test_json_roundtrip(self) -> None:
        from seerflow.lanl.report.schema import Report

        r = self._make_report()
        encoded = msgspec.json.encode(r)
        decoded = msgspec.json.decode(encoded, type=Report)
        assert decoded == r  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_total_events(self) -> None:
        from seerflow.lanl.report.schema import TOTAL_EVENTS

        assert TOTAL_EVENTS == 1_607_452_967

    def test_first_attack_events(self) -> None:
        from seerflow.lanl.report.schema import FIRST_ATTACK_EVENTS

        assert FIRST_ATTACK_EVENTS == 58_655_985

    def test_re_exported_from_init(self) -> None:
        import seerflow.lanl.report as pkg

        assert hasattr(pkg, "TOTAL_EVENTS")
        assert hasattr(pkg, "FIRST_ATTACK_EVENTS")
        assert hasattr(pkg, "Report")
        assert hasattr(pkg, "AccuracySummary")
        assert hasattr(pkg, "Baseline")
