"""Tests for SinkConfig dataclass + AlertingConfig.sinks default (S-361/FR-005)."""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_alerting
from seerflow.config import AlertingConfig, ConfigError, SinkConfig


def test_sinks_default_is_empty_tuple() -> None:
    assert AlertingConfig().sinks == ()


def test_sink_config_is_frozen_and_hashable() -> None:
    s = SinkConfig(type="console", name="ops", formatter="json", min_severity=3)
    assert s.type == "console"
    assert s.name == "ops"
    assert s.formatter == "json"
    assert s.min_severity == 3
    assert s.options == ()
    assert hash(s)  # frozen + slots + tuple options => hashable


def test_sink_config_carries_options_tuple() -> None:
    s = SinkConfig(type="file", name="f1", formatter="json", options=(("path", "/tmp/a.ndjson"),))
    assert s.options == (("path", "/tmp/a.ndjson"),)


# --- Task 4: _build_sinks validator cases ---


def test_build_alerting_parses_sink_list() -> None:
    c = _build_alerting(
        {"sinks": [{"type": "console", "name": "ops", "formatter": "json", "min_severity": 3}]}
    )
    assert len(c.sinks) == 1
    assert c.sinks[0].type == "console"
    assert c.sinks[0].name == "ops"
    assert c.sinks[0].formatter == "json"
    assert c.sinks[0].min_severity == 3


def test_sinks_default_empty_when_absent() -> None:
    assert _build_alerting({}).sinks == ()


def test_unknown_sink_type_raises() -> None:
    with pytest.raises(ConfigError, match="unknown"):
        _build_alerting({"sinks": [{"type": "nonexistent", "name": "x", "formatter": "json"}]})


def test_duplicate_sink_name_raises() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        _build_alerting(
            {
                "sinks": [
                    {"type": "console", "name": "dup", "formatter": "json"},
                    {"type": "console", "name": "dup", "formatter": "slack"},
                ]
            }
        )


def test_invalid_formatter_raises() -> None:
    with pytest.raises(ConfigError, match="formatter"):
        _build_alerting({"sinks": [{"type": "console", "name": "x", "formatter": "xml"}]})


def test_cef_formatter_is_accepted() -> None:
    # S-364: CEF is a selectable sink formatter token (text/line format,
    # decoupled from the dict-POSTing webhook path).
    c = _build_alerting({"sinks": [{"type": "console", "name": "arc", "formatter": "cef"}]})
    assert c.sinks[0].formatter == "cef"


def test_leef_formatter_is_accepted() -> None:
    # S-365: LEEF is a selectable sink formatter token (text/line format,
    # decoupled from the dict-POSTing webhook path).
    c = _build_alerting({"sinks": [{"type": "console", "name": "qradar", "formatter": "leef"}]})
    assert c.sinks[0].formatter == "leef"


def test_sink_min_severity_out_of_range_raises() -> None:
    with pytest.raises(ConfigError, match="min_severity"):
        _build_alerting({"sinks": [{"type": "console", "name": "x", "min_severity": 9}]})


def test_sink_min_severity_bool_rejected() -> None:
    with pytest.raises(ConfigError, match="min_severity"):
        _build_alerting({"sinks": [{"type": "console", "name": "x", "min_severity": True}]})


def test_empty_sink_name_raises() -> None:
    with pytest.raises(ConfigError, match="name"):
        _build_alerting({"sinks": [{"type": "console", "name": "", "formatter": "json"}]})


def test_sinks_not_a_list_raises() -> None:
    with pytest.raises(ConfigError, match="must be a list"):
        _build_alerting({"sinks": {"type": "console"}})


def test_sink_entry_not_a_mapping_raises() -> None:
    with pytest.raises(ConfigError, match="must be a mapping"):
        _build_alerting({"sinks": ["console"]})


def test_sink_options_not_a_mapping_raises() -> None:
    with pytest.raises(ConfigError, match="options"):
        _build_alerting({"sinks": [{"type": "console", "name": "x", "options": ["path"]}]})


# --- S-362: HEC sink config validation (endpoint/token/ca at the boundary) ---


def test_hec_sink_parses_endpoint_and_token() -> None:
    c = _build_alerting(
        {
            "sinks": [
                {
                    "type": "hec",
                    "name": "splunk",
                    "formatter": "json",
                    "options": {
                        "endpoint": "https://splunk.example.com:8088",
                        "token": "tok",
                    },
                }
            ]
        }
    )
    opts = dict(c.sinks[0].options)
    assert opts["endpoint"] == "https://splunk.example.com:8088"
    assert opts["token"] == "tok"


def test_hec_sink_missing_endpoint_raises() -> None:
    with pytest.raises(ConfigError, match="endpoint"):
        _build_alerting({"sinks": [{"type": "hec", "name": "x", "options": {"token": "tok"}}]})


def test_hec_sink_missing_token_raises() -> None:
    with pytest.raises(ConfigError, match="token"):
        _build_alerting(
            {
                "sinks": [
                    {
                        "type": "hec",
                        "name": "x",
                        "options": {"endpoint": "https://splunk:8088"},
                    }
                ]
            }
        )


def test_hec_sink_bad_endpoint_scheme_raises() -> None:
    with pytest.raises(ConfigError, match="http"):
        _build_alerting(
            {
                "sinks": [
                    {
                        "type": "hec",
                        "name": "x",
                        "options": {"endpoint": "ftp://splunk:8088", "token": "t"},
                    }
                ]
            }
        )


def test_hec_sink_private_ip_endpoint_raises() -> None:
    with pytest.raises(ConfigError, match="private"):
        _build_alerting(
            {
                "sinks": [
                    {
                        "type": "hec",
                        "name": "x",
                        "options": {"endpoint": "https://10.0.0.1:8088", "token": "t"},
                    }
                ]
            }
        )


def test_hec_sink_token_env_interpolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The token is env-sourced: ``${VAR}`` in sink options is resolved by the
    loader's interpolation pass, so the secret never lives in the YAML."""
    from seerflow._config_builders import _walk_and_interpolate

    monkeypatch.setenv("_TEST_HEC_TOKEN", "env-sourced-secret")
    raw = _walk_and_interpolate(
        {
            "sinks": [
                {
                    "type": "hec",
                    "name": "x",
                    "options": {
                        "endpoint": "https://splunk:8088",
                        "token": "${_TEST_HEC_TOKEN}",
                    },
                }
            ]
        }
    )
    c = _build_alerting(raw)
    assert dict(c.sinks[0].options)["token"] == "env-sourced-secret"
