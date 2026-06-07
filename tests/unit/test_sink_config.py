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
        _build_alerting({"sinks": [{"type": "hec", "name": "x", "formatter": "json"}]})


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
