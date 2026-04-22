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


@pytest.mark.unit
def test_load_config_rejects_ema_alpha_above_one(tmp_path: Path) -> None:
    """ema_alpha must be in (0, 1]; values > 1 raise ConfigError."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  ema_alpha: 2.0\n")
    with pytest.raises(ConfigError, match=r"ueba\.ema_alpha.*\(0, 1\]"):
        load_config(str(config_path))


@pytest.mark.unit
def test_load_config_rejects_ema_alpha_zero(tmp_path: Path) -> None:
    """ema_alpha must be in (0, 1]; 0 raises ConfigError (open on lower bound)."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  ema_alpha: 0.0\n")
    with pytest.raises(ConfigError, match=r"ueba\.ema_alpha.*\(0, 1\]"):
        load_config(str(config_path))


@pytest.mark.unit
def test_load_config_accepts_ema_alpha_at_upper_bound(tmp_path: Path) -> None:
    """ema_alpha = 1.0 is the inclusive upper bound."""
    config_path = tmp_path / "seerflow.yaml"
    config_path.write_text("ueba:\n  ema_alpha: 1.0\n")
    cfg = load_config(str(config_path))
    assert cfg.ueba.ema_alpha == pytest.approx(1.0)


@pytest.mark.unit
def test_ueba_config_defaults_score_fields() -> None:
    cfg = UEBAConfig()
    assert cfg.score_threshold == pytest.approx(0.75)
    assert cfg.alert_cooldown_seconds == 900
    assert cfg.sub_score_weights.time_of_day == pytest.approx(0.25)
    assert cfg.sub_score_weights.source_novelty == pytest.approx(0.30)
    assert cfg.sub_score_weights.volume == pytest.approx(0.20)
    assert cfg.sub_score_weights.pattern_novelty == pytest.approx(0.25)


@pytest.mark.unit
def test_load_config_roundtrips_ueba_score_fields(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text(
        "ueba:\n"
        "  enabled: true\n"
        "  score_threshold: 0.6\n"
        "  alert_cooldown_seconds: 300\n"
        "  sub_score_weights:\n"
        "    time_of_day: 0.4\n"
        "    source_novelty: 0.3\n"
        "    volume: 0.1\n"
        "    pattern_novelty: 0.2\n"
    )
    cfg = load_config(str(yaml))
    assert cfg.ueba.score_threshold == pytest.approx(0.6)
    assert cfg.ueba.alert_cooldown_seconds == 300
    assert cfg.ueba.sub_score_weights.time_of_day == pytest.approx(0.4)
    assert cfg.ueba.sub_score_weights.source_novelty == pytest.approx(0.3)
    assert cfg.ueba.sub_score_weights.volume == pytest.approx(0.1)
    assert cfg.ueba.sub_score_weights.pattern_novelty == pytest.approx(0.2)


@pytest.mark.unit
def test_load_config_rejects_weights_not_summing_to_one(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text(
        "ueba:\n"
        "  sub_score_weights:\n"
        "    time_of_day: 0.5\n"
        "    source_novelty: 0.5\n"
        "    volume: 0.5\n"
        "    pattern_novelty: 0.5\n"
    )
    with pytest.raises(ConfigError, match="sub_score_weights must sum to 1.0"):
        load_config(str(yaml))


@pytest.mark.unit
def test_load_config_rejects_score_threshold_out_of_range(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text("ueba:\n  score_threshold: 1.5\n")
    with pytest.raises(ConfigError, match=r"ueba\.score_threshold"):
        load_config(str(yaml))


@pytest.mark.unit
def test_load_config_rejects_negative_score_threshold(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text("ueba:\n  score_threshold: -0.1\n")
    with pytest.raises(ConfigError, match=r"ueba\.score_threshold"):
        load_config(str(yaml))


@pytest.mark.unit
def test_load_config_rejects_non_mapping_sub_score_weights(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text("ueba:\n  sub_score_weights: not-a-mapping\n")
    with pytest.raises(ConfigError, match="sub_score_weights must be a mapping"):
        load_config(str(yaml))


@pytest.mark.unit
def test_load_config_rejects_zero_weight(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text(
        "ueba:\n"
        "  sub_score_weights:\n"
        "    time_of_day: 0.0\n"
        "    source_novelty: 0.4\n"
        "    volume: 0.3\n"
        "    pattern_novelty: 0.3\n"
    )
    with pytest.raises(ConfigError, match=r"time_of_day"):
        load_config(str(yaml))


@pytest.mark.unit
def test_load_config_rejects_nonpositive_alert_cooldown(tmp_path: Path) -> None:
    yaml = tmp_path / "seerflow.yaml"
    yaml.write_text("ueba:\n  alert_cooldown_seconds: 0\n")
    with pytest.raises(ConfigError, match=r"alert_cooldown_seconds"):
        load_config(str(yaml))
