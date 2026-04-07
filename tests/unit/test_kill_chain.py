"""Tests for kill-chain state machine tracker (S-096)."""

from __future__ import annotations

import pytest

from seerflow.config import (
    ConfigError,
    KillChainConfig,
    _build_detection,
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
