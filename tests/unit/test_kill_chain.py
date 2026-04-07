"""Tests for kill-chain state machine tracker (S-096)."""

from __future__ import annotations

import uuid

import pytest

from seerflow.config import (
    ConfigError,
    KillChainConfig,
    _build_detection,
)
from seerflow.correlation.kill_chain import KillChainTracker
from seerflow.models.alert import Alert
from seerflow.models.event import SeverityLevel


def _make_alert(
    *,
    entity_uuid: str = "ent-1",
    mitre_tactics: tuple[str, ...] = ("initial-access",),
    timestamp_ns: int = 1_000_000_000_000,
    alert_id: str | None = None,
) -> Alert:
    """Create a minimal Alert for kill-chain tests."""
    return Alert(
        alert_id=alert_id or str(uuid.uuid4()),
        alert_type="ml",
        timestamp_ns=timestamp_ns,
        severity_id=SeverityLevel.WARNING,
        rule_name="test-rule",
        description="test alert",
        entity_uuid=entity_uuid,
        entity_value=entity_uuid[:16],
        entity_type="host",
        contributing_events=(),
        mitre_tactics=mitre_tactics,
    )


# ---------------------------------------------------------------------------
# Task 1: KillChainConfig
# ---------------------------------------------------------------------------


class TestKillChainConfigDefaults:
    def test_defaults(self) -> None:
        cfg = KillChainConfig()
        assert cfg.enabled is True
        assert cfg.tactic_threshold == 3
        assert cfg.window_seconds == 86400
        assert cfg.max_entities == 10_000

    def test_custom_values(self) -> None:
        cfg = KillChainConfig(
            enabled=False,
            tactic_threshold=5,
            window_seconds=3600,
            max_entities=500,
        )
        assert cfg.enabled is False
        assert cfg.tactic_threshold == 5
        assert cfg.window_seconds == 3600
        assert cfg.max_entities == 500

    def test_frozen(self) -> None:
        cfg = KillChainConfig()
        with pytest.raises(AttributeError):
            cfg.tactic_threshold = 10  # type: ignore[misc]


class TestKillChainConfigValidation:
    def test_threshold_below_2_raises(self) -> None:
        with pytest.raises(ConfigError, match=r"kill_chain\.tactic_threshold"):
            _build_detection({"kill_chain": {"tactic_threshold": 1}})

    def test_window_below_60_raises(self) -> None:
        with pytest.raises(ConfigError, match=r"kill_chain\.window_seconds"):
            _build_detection({"kill_chain": {"window_seconds": 59}})

    def test_max_entities_below_1_raises(self) -> None:
        with pytest.raises(ConfigError, match=r"kill_chain\.max_entities"):
            _build_detection({"kill_chain": {"max_entities": 0}})

    def test_detection_config_has_kill_chain(self) -> None:
        cfg = _build_detection({})
        assert hasattr(cfg, "kill_chain")
        assert isinstance(cfg.kill_chain, KillChainConfig)

    def test_kill_chain_from_yaml_section(self) -> None:
        cfg = _build_detection({"kill_chain": {"tactic_threshold": 4, "window_seconds": 7200}})
        assert cfg.kill_chain.tactic_threshold == 4
        assert cfg.kill_chain.window_seconds == 7200

    def test_kill_chain_ignores_unknown_keys(self) -> None:
        cfg = _build_detection({"kill_chain": {"tactic_threshold": 4, "unknown_key": True}})
        assert cfg.kill_chain.tactic_threshold == 4

    def test_kill_chain_disabled(self) -> None:
        cfg = _build_detection({"kill_chain": {"enabled": False}})
        assert cfg.kill_chain.enabled is False

    def test_tracker_disabled_returns_empty(self) -> None:
        tracker = KillChainTracker(KillChainConfig(enabled=False))
        alert = _make_alert(mitre_tactics=("initial-access",))
        assert tracker.record_alert(alert) == []


# ---------------------------------------------------------------------------
# Task 2: KillChainTracker — record + eviction
# ---------------------------------------------------------------------------


class TestKillChainTrackerRecord:
    def test_record_stores_tactic(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=5))
        alert = _make_alert(mitre_tactics=("initial-access",))
        tracker.record_alert(alert)
        state = tracker.get_entity_state("ent-1")
        assert "initial-access" in state

    def test_record_multiple_tactics(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=5))
        tracker.record_alert(_make_alert(mitre_tactics=("initial-access",), timestamp_ns=1000))
        tracker.record_alert(_make_alert(mitre_tactics=("execution",), timestamp_ns=2000))
        state = tracker.get_entity_state("ent-1")
        assert len(state) == 2
        assert "initial-access" in state
        assert "execution" in state

    def test_eviction_removes_stale_tactics(self) -> None:
        cfg = KillChainConfig(tactic_threshold=5, window_seconds=60)
        tracker = KillChainTracker(cfg)
        early_ns = 1_000_000_000_000
        tracker.record_alert(_make_alert(mitre_tactics=("initial-access",), timestamp_ns=early_ns))
        late_ns = early_ns + 61 * 1_000_000_000
        tracker.record_alert(_make_alert(mitre_tactics=("execution",), timestamp_ns=late_ns))
        state = tracker.get_entity_state("ent-1")
        assert "initial-access" not in state
        assert "execution" in state

    def test_skip_empty_tactics(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=5))
        result = tracker.record_alert(_make_alert(mitre_tactics=()))
        assert result == []
        assert tracker.get_entity_state("ent-1") == {}

    def test_skip_empty_entity(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=5))
        result = tracker.record_alert(
            _make_alert(entity_uuid="", mitre_tactics=("initial-access",))
        )
        assert result == []

    def test_max_entities_lru_eviction(self) -> None:
        cfg = KillChainConfig(tactic_threshold=5, max_entities=2)
        tracker = KillChainTracker(cfg)
        tracker.record_alert(
            _make_alert(entity_uuid="e1", mitre_tactics=("tactic-a",), timestamp_ns=1000)
        )
        tracker.record_alert(
            _make_alert(entity_uuid="e2", mitre_tactics=("tactic-b",), timestamp_ns=2000)
        )
        tracker.record_alert(
            _make_alert(entity_uuid="e3", mitre_tactics=("tactic-c",), timestamp_ns=3000)
        )
        assert tracker.get_entity_state("e1") == {}
        assert "tactic-b" in tracker.get_entity_state("e2")
        assert "tactic-c" in tracker.get_entity_state("e3")


# ---------------------------------------------------------------------------
# Task 3: Kill-chain threshold alert
# ---------------------------------------------------------------------------


class TestKillChainThresholdAlert:
    def test_alert_at_threshold(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=3))
        tracker.record_alert(_make_alert(mitre_tactics=("initial-access",), timestamp_ns=1000))
        tracker.record_alert(_make_alert(mitre_tactics=("execution",), timestamp_ns=2000))
        result = tracker.record_alert(
            _make_alert(mitre_tactics=("persistence",), timestamp_ns=3000)
        )
        assert len(result) == 1
        assert result[0].alert_type == "correlation"
        assert result[0].rule_name == "kill-chain-progression"

    def test_no_alert_below_threshold(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=3))
        tracker.record_alert(_make_alert(mitre_tactics=("initial-access",), timestamp_ns=1000))
        result = tracker.record_alert(_make_alert(mitre_tactics=("execution",), timestamp_ns=2000))
        assert result == []

    def test_alert_includes_all_tactics(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=3))
        tracker.record_alert(_make_alert(mitre_tactics=("initial-access",), timestamp_ns=1000))
        tracker.record_alert(_make_alert(mitre_tactics=("execution",), timestamp_ns=2000))
        result = tracker.record_alert(
            _make_alert(mitre_tactics=("persistence",), timestamp_ns=3000)
        )
        assert len(result) == 1
        alert = result[0]
        assert set(alert.mitre_tactics) == {
            "initial-access",
            "execution",
            "persistence",
        }

    def test_dedup_key_format(self) -> None:
        tracker = KillChainTracker(KillChainConfig(tactic_threshold=3))
        tracker.record_alert(
            _make_alert(
                entity_uuid="abc-123",
                mitre_tactics=("initial-access",),
                timestamp_ns=1000,
            )
        )
        tracker.record_alert(
            _make_alert(
                entity_uuid="abc-123",
                mitre_tactics=("execution",),
                timestamp_ns=2000,
            )
        )
        result = tracker.record_alert(
            _make_alert(
                entity_uuid="abc-123",
                mitre_tactics=("persistence",),
                timestamp_ns=3000,
            )
        )
        assert len(result) == 1
        assert result[0].dedup_key == "kill-chain:abc-123"
