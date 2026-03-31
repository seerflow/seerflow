"""Tests for per-entity risk accumulation."""

from __future__ import annotations

import dataclasses
import time

import pytest

from seerflow.correlation.risk import RiskEntry, RiskRegister


def _make_entry(
    *,
    risk_points: float = 10.0,
    source: str = "ml",
    rule_name: str = "hst-anomaly",
    mitre_tactics: tuple[str, ...] = (),
    mitre_techniques: tuple[str, ...] = (),
    timestamp_ns: int | None = None,
) -> RiskEntry:
    if timestamp_ns is None:
        timestamp_ns = time.time_ns()
    return RiskEntry(
        timestamp_ns=timestamp_ns,
        risk_points=risk_points,
        source=source,
        rule_name=rule_name,
        mitre_tactics=mitre_tactics,
        mitre_techniques=mitre_techniques,
    )


class TestRiskEntry:
    def test_is_frozen_dataclass(self) -> None:
        entry = _make_entry()
        assert dataclasses.is_dataclass(entry)
        with pytest.raises(AttributeError):
            entry.risk_points = 99.0  # type: ignore[misc]


class TestRiskRegister:
    def test_add_risk_returns_current_score(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        entry = _make_entry(risk_points=10.0)
        score = reg.add_risk("entity-a", entry)
        assert score > 0

    def test_get_risk_unknown_entity_returns_zero(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        assert reg.get_risk("nonexistent") == 0.0

    def test_risk_accumulates_across_entries(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        e1 = _make_entry(risk_points=10.0)
        e2 = _make_entry(risk_points=15.0)
        reg.add_risk("entity-a", e1)
        score = reg.add_risk("entity-a", e2)
        assert score > 10.0  # More than a single entry

    def test_exponential_decay_reduces_old_entries(self) -> None:
        half_life_ns = 1_000_000_000  # 1 second
        reg = RiskRegister(
            half_life_ns=half_life_ns,
            threshold=100.0,
            max_entities=1000,
        )
        now = time.time_ns()
        old = now - 5 * half_life_ns  # 5 half-lives ago
        entry = _make_entry(risk_points=100.0, timestamp_ns=old)
        reg.add_risk("entity-a", entry)
        score = reg.get_risk("entity-a")
        # After 5 half-lives, score should be ~3.125 (100 * 0.5^5)
        assert score < 5.0

    def test_check_threshold_returns_true_when_exceeded(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=20.0,
            max_entities=1000,
        )
        reg.add_risk("entity-a", _make_entry(risk_points=25.0))
        assert reg.check_threshold("entity-a") is True

    def test_check_threshold_returns_false_when_below(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        reg.add_risk("entity-a", _make_entry(risk_points=5.0))
        assert reg.check_threshold("entity-a") is False

    def test_lru_eviction_when_max_entities_exceeded(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=2,
        )
        reg.add_risk("entity-a", _make_entry(risk_points=10.0))
        reg.add_risk("entity-b", _make_entry(risk_points=10.0))
        reg.add_risk("entity-c", _make_entry(risk_points=10.0))
        # entity-a should be evicted
        assert reg.get_risk("entity-a") == 0.0
        assert reg.get_risk("entity-b") > 0
        assert reg.get_risk("entity-c") > 0

    def test_future_timestamp_clamps_age_to_zero(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        future = time.time_ns() + 60 * 1_000_000_000  # 60 seconds in the future
        entry = _make_entry(risk_points=50.0, timestamp_ns=future)
        reg.add_risk("entity-a", entry)
        score = reg.get_risk("entity-a")
        # Future timestamp should not inflate score; clamped to age=0
        assert score == pytest.approx(50.0, abs=0.1)

    def test_entity_count_property(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        assert reg.entity_count == 0
        reg.add_risk("entity-a", _make_entry(risk_points=10.0))
        assert reg.entity_count == 1
        reg.add_risk("entity-b", _make_entry(risk_points=10.0))
        assert reg.entity_count == 2

    def test_mitre_tags_preserved_in_entries(self) -> None:
        reg = RiskRegister(
            half_life_ns=4 * 3600 * 1_000_000_000,
            threshold=100.0,
            max_entities=1000,
        )
        entry = _make_entry(
            mitre_tactics=("credential-access",),
            mitre_techniques=("T1110.001",),
        )
        reg.add_risk("entity-a", entry)
        entries = reg.get_entries("entity-a")
        assert len(entries) == 1
        assert entries[0].mitre_tactics == ("credential-access",)
