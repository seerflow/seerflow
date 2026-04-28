"""Unit tests for ThreatIntelConfig and friends."""

from __future__ import annotations

import pytest

from seerflow.config import (
    SeerflowConfig,
    TAXIIAuthConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)


def test_threat_intel_disabled_by_default() -> None:
    cfg = SeerflowConfig()
    assert cfg.threat_intel.enabled is False
    assert cfg.threat_intel.feeds == ()


def test_taxii_feed_config_is_frozen() -> None:
    feed = TAXIIFeedConfig(
        id="otx",
        url="https://otx.example/taxii/",
        collection_id="collection-uuid",
    )
    with pytest.raises(AttributeError):
        feed.id = "changed"  # type: ignore[misc]


def test_taxii_auth_api_key_kind() -> None:
    auth = TAXIIAuthConfig(kind="api_key", api_key_env="OTX_API_KEY")
    assert auth.kind == "api_key"
    assert auth.api_key_env == "OTX_API_KEY"
    assert auth.api_key_header == "Authorization"


def test_threat_intel_config_defaults() -> None:
    cfg = ThreatIntelConfig()
    assert cfg.default_poll_interval_s == 3600
    assert cfg.request_timeout_s == 30.0
    assert cfg.max_indicators_per_feed == 1_000_000
    assert cfg.expired_grace_days == 30
    assert cfg.startup_jitter_s == 30
