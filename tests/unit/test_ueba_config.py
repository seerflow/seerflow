"""Unit tests for UEBAConfig (S-064)."""

from __future__ import annotations

import pytest

from seerflow.config import SeerflowConfig, UEBAConfig


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
    assert cfg.flush_interval_s == 300


@pytest.mark.unit
def test_seerflow_config_exposes_ueba_block() -> None:
    cfg = SeerflowConfig()
    assert cfg.ueba.enabled is True
