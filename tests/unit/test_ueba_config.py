"""Unit tests for UEBAConfig (S-064)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from seerflow.config import ConfigError, SeerflowConfig, UEBAConfig, load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_ueba_config_defaults() -> None:
    cfg = UEBAConfig()
    assert cfg.enabled is True
    assert cfg.warmup_days == 7
    assert cfg.warmup_min_events == 50
    assert cfg.max_entities == 100_000
    assert cfg.ema_alpha == pytest.approx(0.05)
    assert cfg.source_ip_cap == 64
    assert cfg.template_top_k == 32


@pytest.mark.unit
def test_seerflow_config_exposes_ueba_block() -> None:
    cfg = SeerflowConfig()
    assert cfg.ueba.enabled is True


@pytest.mark.unit
def test_load_config_roundtrips_ueba_block(tmp_path: Path) -> None:
    """YAML ``ueba:`` block must flow through ``load_config`` end-to-end."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text(
        "ueba:\n"
        "  enabled: false\n"
        "  warmup_days: 2\n"
        "  warmup_min_events: 10\n"
        "  max_entities: 500\n"
        "  ema_alpha: 0.1\n"
        "  source_ip_cap: 16\n"
        "  template_top_k: 8\n"
    )
    cfg = load_config(str(config_path))
    assert cfg.ueba.enabled is False
    assert cfg.ueba.warmup_days == 2
    assert cfg.ueba.warmup_min_events == 10
    assert cfg.ueba.max_entities == 500
    assert cfg.ueba.ema_alpha == pytest.approx(0.1)
    assert cfg.ueba.source_ip_cap == 16
    assert cfg.ueba.template_top_k == 8


@pytest.mark.unit
def test_load_config_defaults_when_ueba_block_missing(tmp_path: Path) -> None:
    """Omitted ``ueba:`` block still yields UEBAConfig defaults."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("log_level: INFO\n")
    cfg = load_config(str(config_path))
    assert cfg.ueba == UEBAConfig()


@pytest.mark.unit
def test_load_config_rejects_non_int_warmup_days(tmp_path: Path) -> None:
    """warmup_days must be an int; strings raise ConfigError."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  warmup_days: seven\n")
    with pytest.raises(ConfigError, match=r"ueba\.warmup_days"):
        load_config(str(config_path))


@pytest.mark.unit
def test_load_config_rejects_non_bool_enabled(tmp_path: Path) -> None:
    """enabled must be a bool; ints raise ConfigError."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  enabled: 1\n")
    with pytest.raises(ConfigError, match=r"ueba\.enabled"):
        load_config(str(config_path))


@pytest.mark.unit
def test_load_config_rejects_non_number_ema_alpha(tmp_path: Path) -> None:
    """ema_alpha must be a number; strings raise ConfigError."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  ema_alpha: fast\n")
    with pytest.raises(ConfigError, match=r"ueba\.ema_alpha"):
        load_config(str(config_path))
