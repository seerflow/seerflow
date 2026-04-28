"""S-226 — verify the new _threat_intel_builders module exposes the expected surface."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

from seerflow._config_validation import ConfigError
from seerflow._threat_intel_builders import (
    _build_taxii_auth_config,
    _build_taxii_feed_config,
    _build_threat_intel_config,
    _require_taxii_bool,
    _require_taxii_int,
    _require_taxii_optional_int,
    _require_taxii_str,
    build_seerflow_config,
)


def test_module_imports() -> None:
    mod = importlib.import_module("seerflow._threat_intel_builders")
    for name in (
        "_build_taxii_auth_config",
        "_build_taxii_feed_config",
        "_require_taxii_str",
        "_require_taxii_int",
        "_require_taxii_optional_int",
        "_require_taxii_bool",
        "_require_taxii_auth",
        "_build_threat_intel_config",
        "build_seerflow_config",
    ):
        assert hasattr(mod, name), f"missing {name}"


def test_module_loads_as_entry_point() -> None:
    """Direct `import seerflow._threat_intel_builders` from a clean process must succeed.

    Regression guard: the original implementation imported `_walk_and_interpolate`
    at module top-level, which triggered a circular ImportError when this module
    was the first thing loaded.
    """
    proc = subprocess.run(  # noqa: S603 — fixed args, sys.executable is trusted
        [sys.executable, "-c", "import seerflow._threat_intel_builders"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"clean import failed: {proc.stderr}"


def test_build_seerflow_config_default() -> None:
    cfg = build_seerflow_config({})
    assert cfg.threat_intel.enabled is False
    assert cfg.threat_intel.feeds == ()


def test_build_seerflow_config_round_trip_with_auth() -> None:
    raw = {
        "threat_intel": {
            "enabled": True,
            "feeds": [
                {
                    "id": "otx",
                    "url": "https://otx.example/taxii/",
                    "collection_id": "abc",
                    "auth": {
                        "kind": "api_key",
                        "api_key_env": "OTX_KEY",
                        "api_key_header": "X-OTX-API-KEY",
                    },
                }
            ],
        }
    }
    cfg = build_seerflow_config(raw)
    assert cfg.threat_intel.enabled is True
    feed = cfg.threat_intel.feeds[0]
    assert feed.id == "otx"
    assert feed.auth is not None
    assert feed.auth.kind == "api_key"
    assert feed.auth.api_key_header == "X-OTX-API-KEY"


def test_require_taxii_str_rejects_empty() -> None:
    with pytest.raises(ConfigError, match="must be a non-empty string"):
        _require_taxii_str({"id": ""}, "id")


def test_require_taxii_int_rejects_bool() -> None:
    with pytest.raises(ConfigError, match="must be an int"):
        _require_taxii_int({"x": True}, "x", default=0)


def test_require_taxii_optional_int_passes_through_none() -> None:
    assert _require_taxii_optional_int({}, "x") is None


def test_require_taxii_bool_rejects_non_bool() -> None:
    with pytest.raises(ConfigError, match="must be a bool"):
        _require_taxii_bool({"x": "yes"}, "x", default=False)


def test_build_taxii_auth_config_rejects_unknown_kind() -> None:
    with pytest.raises(ConfigError, match="must be 'api_key' or 'basic'"):
        _build_taxii_auth_config({"kind": "oauth"})


def test_build_taxii_feed_config_rejects_non_mapping() -> None:
    with pytest.raises(ConfigError, match="must be mappings"):
        _build_taxii_feed_config("not-a-dict")  # type: ignore[arg-type]


def test_build_threat_intel_config_rejects_non_mapping_feeds() -> None:
    with pytest.raises(ConfigError, match=r"threat_intel\.feeds must be a list"):
        _build_threat_intel_config({"feeds": "not-a-list"})


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"kind": "api_key", "api_key_env": 123}, "api_key_env must be a string"),
        ({"kind": "api_key", "api_key_header": ""}, "api_key_header must be a non-empty"),
        ({"kind": "basic", "username_env": 5}, "username_env must be a string"),
        ({"kind": "basic", "password_env": 5}, "password_env must be a string"),
    ],
)
def test_build_taxii_auth_config_field_validation(data: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _build_taxii_auth_config(data)


def test_require_taxii_int_rejects_string() -> None:
    with pytest.raises(ConfigError, match="must be an int"):
        _require_taxii_int({"x": "10"}, "x", default=0)


def test_require_taxii_optional_int_rejects_bool() -> None:
    with pytest.raises(ConfigError, match="must be an int or omitted"):
        _require_taxii_optional_int({"x": True}, "x")


def test_build_threat_intel_config_passthrough_none_feeds() -> None:
    cfg = _build_threat_intel_config({"enabled": False, "feeds": None})
    assert cfg.feeds == ()


def test_build_threat_intel_config_rejects_non_mapping() -> None:
    with pytest.raises(ConfigError, match="threat_intel must be a mapping"):
        _build_threat_intel_config([1])  # type: ignore[arg-type]


def test_build_threat_intel_config_rejects_non_bool_enabled() -> None:
    with pytest.raises(ConfigError, match=r"threat_intel\.enabled must be a bool"):
        _build_threat_intel_config({"enabled": "yes"})


def test_require_taxii_auth_rejects_non_mapping() -> None:
    from seerflow._threat_intel_builders import _require_taxii_auth

    with pytest.raises(ConfigError, match="auth must be a mapping or omitted"):
        _require_taxii_auth({"auth": "not-a-dict"})


@pytest.mark.parametrize(
    ("field", "bad_value", "match"),
    [
        ("default_poll_interval_s", "1h", r"default_poll_interval_s must be an int"),
        ("request_timeout_s", "fast", r"request_timeout_s must be a number"),
        ("max_indicators_per_feed", "lots", r"max_indicators_per_feed must be an int"),
        ("expired_grace_days", "30d", r"expired_grace_days must be an int"),
        ("startup_jitter_s", "30s", r"startup_jitter_s must be an int"),
    ],
)
def test_build_threat_intel_config_numeric_field_validation(
    field: str, bad_value: str, match: str
) -> None:
    with pytest.raises(ConfigError, match=match):
        _build_threat_intel_config({field: bad_value})


def test_config_builders_lazy_reexport() -> None:
    """The PEP 562 __getattr__ on _config_builders re-exports build_seerflow_config."""
    from seerflow import _config_builders

    func = _config_builders.build_seerflow_config
    assert func({}).threat_intel.enabled is False
    with pytest.raises(AttributeError):
        _ = _config_builders.does_not_exist  # type: ignore[attr-defined]
