"""Config-boundary validation for the syslog sink (S-363/FR-002).

Mirrors the HEC config tests: every transport option is validated at the
``alerting.sinks`` boundary so a malformed entry fails fast with a clear
``ConfigError`` rather than crashing at delivery time.
"""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_alerting
from seerflow.config import ConfigError


def _syslog_entry(**options: object) -> dict[str, object]:
    base: dict[str, object] = {"host": "collector.example.com"}
    base.update(options)
    return {"type": "syslog", "name": "sl", "formatter": "cef", "options": base}


def test_syslog_sink_parses_with_defaults() -> None:
    cfg = _build_alerting({"sinks": [_syslog_entry()]})
    sink = cfg.sinks[0]
    assert sink.type == "syslog"
    assert dict(sink.options)["host"] == "collector.example.com"
    assert dict(sink.options)["port"] == "514"
    assert dict(sink.options)["facility"] == "1"
    assert dict(sink.options)["transport"] == "udp"


def test_syslog_sink_accepts_explicit_options() -> None:
    cfg = _build_alerting({"sinks": [_syslog_entry(port=1514, facility=16, transport="tcp")]})
    opts = dict(cfg.sinks[0].options)
    assert opts["port"] == "1514"
    assert opts["facility"] == "16"
    assert opts["transport"] == "tcp"


def test_syslog_sink_missing_host_raises() -> None:
    with pytest.raises(ConfigError, match="host"):
        _build_alerting({"sinks": [{"type": "syslog", "name": "x", "options": {}}]})


def test_syslog_sink_bad_transport_raises() -> None:
    with pytest.raises(ConfigError, match="transport"):
        _build_alerting({"sinks": [_syslog_entry(transport="smoke-signal")]})


def test_syslog_sink_port_out_of_range_raises() -> None:
    with pytest.raises(ConfigError, match="port"):
        _build_alerting({"sinks": [_syslog_entry(port=99999)]})


def test_syslog_sink_port_zero_raises() -> None:
    with pytest.raises(ConfigError, match="port"):
        _build_alerting({"sinks": [_syslog_entry(port=0)]})


def test_syslog_sink_facility_out_of_range_raises() -> None:
    with pytest.raises(ConfigError, match="facility"):
        _build_alerting({"sinks": [_syslog_entry(facility=24)]})


def test_syslog_sink_facility_negative_raises() -> None:
    with pytest.raises(ConfigError, match="facility"):
        _build_alerting({"sinks": [_syslog_entry(facility=-1)]})


def test_syslog_does_not_disturb_hec_validation() -> None:
    """Both sink kinds validate independently in one config block."""
    cfg = _build_alerting(
        {
            "sinks": [
                {
                    "type": "hec",
                    "name": "splunk",
                    "options": {
                        "endpoint": "https://splunk.example.com:8088",
                        "token": "tok",
                    },
                },
                _syslog_entry(transport="tcp"),
            ]
        }
    )
    assert {s.type for s in cfg.sinks} == {"hec", "syslog"}
