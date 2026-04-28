"""YAML-loader + validator tests for threat_intel.feeds."""

from __future__ import annotations

import pytest

from seerflow._config_builders import build_seerflow_config
from seerflow._config_validation import ConfigError, validate_seerflow_config


def test_loader_parses_minimal_taxii_feed() -> None:
    raw = {
        "threat_intel": {
            "enabled": True,
            "feeds": [
                {
                    "id": "otx",
                    "url": "https://otx.example/taxii/",
                    "collection_id": "abc-123",
                }
            ],
        }
    }
    cfg = build_seerflow_config(raw)
    assert cfg.threat_intel.enabled is True
    assert len(cfg.threat_intel.feeds) == 1
    feed = cfg.threat_intel.feeds[0]
    assert feed.id == "otx"
    assert feed.auth is None


def test_loader_parses_api_key_auth() -> None:
    raw = {
        "threat_intel": {
            "feeds": [
                {
                    "id": "otx",
                    "url": "https://otx.example/taxii/",
                    "collection_id": "x",
                    "auth": {"kind": "api_key", "api_key_env": "OTX_API_KEY"},
                }
            ],
        }
    }
    cfg = build_seerflow_config(raw)
    auth = cfg.threat_intel.feeds[0].auth
    assert auth is not None
    assert auth.kind == "api_key"
    assert auth.api_key_env == "OTX_API_KEY"


def test_validator_rejects_http_without_opt_in() -> None:
    raw = {
        "threat_intel": {
            "enabled": True,
            "feeds": [{"id": "x", "url": "http://insecure.example/taxii/", "collection_id": "c"}],
        }
    }
    cfg = build_seerflow_config(raw)
    with pytest.raises(ConfigError, match="https"):
        validate_seerflow_config(cfg)


def test_validator_rejects_short_poll_interval() -> None:
    raw = {
        "threat_intel": {
            "enabled": True,
            "feeds": [
                {
                    "id": "x",
                    "url": "https://x.example/taxii/",
                    "collection_id": "c",
                    "poll_interval_s": 5,
                }
            ],
        }
    }
    cfg = build_seerflow_config(raw)
    with pytest.raises(ConfigError, match="poll_interval"):
        validate_seerflow_config(cfg)


def test_validator_rejects_duplicate_feed_ids() -> None:
    raw = {
        "threat_intel": {
            "enabled": True,
            "feeds": [
                {"id": "x", "url": "https://a.example/taxii/", "collection_id": "c"},
                {"id": "x", "url": "https://b.example/taxii/", "collection_id": "c"},
            ],
        }
    }
    cfg = build_seerflow_config(raw)
    with pytest.raises(ConfigError, match="duplicate"):
        validate_seerflow_config(cfg)


def test_validator_disabled_block_skips_validation() -> None:
    raw = {
        "threat_intel": {
            "enabled": False,
            "feeds": [{"id": "x", "url": "http://insecure.example/", "collection_id": "c"}],
        }
    }
    cfg = build_seerflow_config(raw)
    # disabled -> validator must not raise
    validate_seerflow_config(cfg)
