"""Tests for AlertingConfig console.* fields + validation (S-312/FR-071)."""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_alerting
from seerflow.config import AlertingConfig, ConfigError


def test_defaults_are_safe() -> None:
    c = AlertingConfig()
    assert c.console_enabled is False
    assert c.console_stream == "stdout"
    assert c.console_format == "human"
    assert c.console_min_severity == 0


def test_build_alerting_reads_console_block() -> None:
    c = _build_alerting(
        {
            "console_enabled": True,
            "console_stream": "stderr",
            "console_format": "json",
            "console_min_severity": 3,
        }
    )
    assert c.console_enabled is True
    assert c.console_stream == "stderr"
    assert c.console_format == "json"
    assert c.console_min_severity == 3


def test_build_alerting_console_defaults_when_absent() -> None:
    c = _build_alerting({})
    assert c.console_enabled is False
    assert c.console_stream == "stdout"
    assert c.console_format == "human"
    assert c.console_min_severity == 0


def test_invalid_console_stream_raises() -> None:
    with pytest.raises(ConfigError, match="console_stream"):
        _build_alerting({"console_stream": "syslog"})


def test_invalid_console_format_raises() -> None:
    with pytest.raises(ConfigError, match="console_format"):
        _build_alerting({"console_format": "xml"})


def test_invalid_console_min_severity_out_of_range_raises() -> None:
    with pytest.raises(ConfigError, match="console_min_severity"):
        _build_alerting({"console_min_severity": 9})


def test_invalid_console_min_severity_non_int_raises() -> None:
    with pytest.raises(ConfigError, match="console_min_severity"):
        _build_alerting({"console_min_severity": "high"})


def test_console_min_severity_bool_rejected() -> None:
    with pytest.raises(ConfigError, match="console_min_severity"):
        _build_alerting({"console_min_severity": True})
