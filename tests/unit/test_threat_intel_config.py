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


# --- S-227 Task 1: _resolve_feed_with_private_ip_guard ----------------------


def test_resolve_feed_with_private_ip_guard_returns_literal_public_ip() -> None:
    from seerflow._config_validation import _resolve_feed_with_private_ip_guard

    assert _resolve_feed_with_private_ip_guard("feed-x", "1.1.1.1") == "1.1.1.1"


def test_resolve_feed_with_private_ip_guard_rejects_literal_private_ip() -> None:
    from seerflow._config_validation import (
        ConfigError,
        _resolve_feed_with_private_ip_guard,
    )

    with pytest.raises(ConfigError, match="private/reserved"):
        _resolve_feed_with_private_ip_guard("feed-x", "10.0.0.1")


def test_resolve_feed_with_private_ip_guard_returns_resolved_ip_for_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from seerflow import _config_validation as cv

    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "8.8.8.8")
    assert cv._resolve_feed_with_private_ip_guard("feed-x", "taxii.example") == "8.8.8.8"


def test_resolve_feed_with_private_ip_guard_rejects_resolved_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    from seerflow import _config_validation as cv

    monkeypatch.setattr(socket, "gethostbyname", lambda _h: "169.254.169.254")
    with pytest.raises(cv.ConfigError, match="private/reserved"):
        cv._resolve_feed_with_private_ip_guard("feed-x", "imds.example")


def test_resolve_feed_with_private_ip_guard_rejects_literal_multicast() -> None:
    """Defence in depth: multicast addresses should be rejected even though
    the kernel rejects unicast TCP to them. Reviewer 5 (security) low.
    """
    from seerflow._config_validation import (
        ConfigError,
        _resolve_feed_with_private_ip_guard,
    )

    with pytest.raises(ConfigError, match="private/reserved"):
        _resolve_feed_with_private_ip_guard("feed-x", "224.0.0.1")


# --- S-227 Task 2: max_indicators_per_feed bounds --------------------------


def test_max_indicators_per_feed_hard_cap_rejects_over_10m() -> None:
    from seerflow._config_validation import (
        ConfigError,
        _validate_threat_intel_defaults,
    )

    cfg = ThreatIntelConfig(enabled=True, max_indicators_per_feed=10_000_001)
    with pytest.raises(ConfigError, match="max_indicators_per_feed"):
        _validate_threat_intel_defaults(cfg)


def test_max_indicators_per_feed_warn_logs_above_threshold(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from seerflow._config_validation import _validate_threat_intel_defaults

    cfg = ThreatIntelConfig(enabled=True, max_indicators_per_feed=2_000_000)
    with caplog.at_level(logging.WARNING, logger="seerflow"):
        _validate_threat_intel_defaults(cfg)
    assert any(
        "max_indicators_per_feed=2000000" in rec.message and ">100 MB" in rec.message
        for rec in caplog.records
    )


def test_max_indicators_per_feed_default_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    from seerflow._config_validation import _validate_threat_intel_defaults

    cfg = ThreatIntelConfig(enabled=True)  # default 1_000_000
    with caplog.at_level(logging.WARNING, logger="seerflow"):
        _validate_threat_intel_defaults(cfg)
    assert not any("max_indicators_per_feed" in rec.message for rec in caplog.records)


# --- S-068 Task 5: IoCMatcherConfig builder --------------------------------


def test_threat_intel_matcher_block_defaults() -> None:
    from seerflow._threat_intel_builders import _build_threat_intel_config

    cfg = _build_threat_intel_config({})
    assert cfg.matcher.enabled is False
    assert cfg.matcher.fpr == 0.001
    assert cfg.matcher.min_capacity == 100_000
    assert cfg.matcher.capacity_growth_factor == 1.25
    assert cfg.matcher.confidence_floor == 0
    assert cfg.matcher.rebuild_debounce_ms == 200
    assert cfg.matcher.enabled_types == (
        "ipv4",
        "ipv6",
        "domain",
        "url",
        "md5",
        "sha1",
        "sha256",
    )


def test_threat_intel_matcher_block_overrides() -> None:
    from seerflow._threat_intel_builders import _build_threat_intel_config

    cfg = _build_threat_intel_config(
        {
            "matcher": {
                "enabled": True,
                "fpr": 0.01,
                "min_capacity": 1_000,
                "capacity_growth_factor": 2.0,
                "confidence_floor": 50,
                "rebuild_debounce_ms": 0,
                "enabled_types": ["ipv4", "domain"],
            }
        }
    )
    assert cfg.matcher.enabled is True
    assert cfg.matcher.fpr == 0.01
    assert cfg.matcher.confidence_floor == 50
    assert cfg.matcher.enabled_types == ("ipv4", "domain")


# --- S-068 Task 6: IoCMatcherConfig validation -----------------------------


def test_matcher_validation_rejects_bad_fpr() -> None:
    from seerflow._config_validation import ConfigError, validate_seerflow_config
    from seerflow._threat_intel_builders import _build_threat_intel_config
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig(
        threat_intel=_build_threat_intel_config({"matcher": {"enabled": True, "fpr": 0.0}})
    )
    with pytest.raises(ConfigError, match="fpr"):
        validate_seerflow_config(cfg)


def test_matcher_validation_rejects_unknown_type() -> None:
    from seerflow._config_validation import ConfigError, validate_seerflow_config
    from seerflow._threat_intel_builders import _build_threat_intel_config
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig(
        threat_intel=_build_threat_intel_config(
            {"matcher": {"enabled": True, "enabled_types": ["bogus"]}}
        )
    )
    with pytest.raises(ConfigError, match="enabled_types"):
        validate_seerflow_config(cfg)


def test_matcher_validation_rejects_negative_growth_factor() -> None:
    from seerflow._config_validation import ConfigError, validate_seerflow_config
    from seerflow._threat_intel_builders import _build_threat_intel_config
    from seerflow.config import SeerflowConfig

    cfg = SeerflowConfig(
        threat_intel=_build_threat_intel_config(
            {"matcher": {"enabled": True, "capacity_growth_factor": 0.5}}
        )
    )
    with pytest.raises(ConfigError, match="capacity_growth_factor"):
        validate_seerflow_config(cfg)
