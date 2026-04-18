"""Config parsing for alerting.routing_rules, default_routing, quiet_hours."""

from __future__ import annotations

import pytest

from seerflow._config_builders import _build_alerting
from seerflow._config_validation import ConfigError


def _yaml_alerting(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "webhooks": [
            {"name": "oncall-slack", "url": "https://slack/hook", "format": "slack"},
            {"name": "team-email", "url": "https://email/hook", "format": "json"},
        ],
    }
    base.update(extra)
    return base


@pytest.mark.unit
def test_routing_rules_parse_valid_config() -> None:
    cfg = _build_alerting(
        _yaml_alerting(
            routing_rules=[
                {
                    "match": {
                        "alert_type": "sigma",
                        "rule_name": "brute-force*",
                        "min_severity": 3,
                    },
                    "notify": [
                        {"channel": "oncall-slack", "mode": "immediate"},
                    ],
                },
                {
                    "match": {},
                    "notify": [
                        {
                            "channel": "team-email",
                            "mode": "digest",
                            "digest_window_minutes": 30,
                        }
                    ],
                },
            ]
        )
    )
    assert len(cfg.routing_rules) == 2
    assert cfg.routing_rules[0].match.rule_name == "brute-force*"
    assert cfg.routing_rules[1].notify[0].mode == "digest"


@pytest.mark.unit
def test_unknown_channel_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown channel"):
        _build_alerting(
            _yaml_alerting(
                routing_rules=[
                    {
                        "match": {},
                        "notify": [{"channel": "nope", "mode": "immediate"}],
                    }
                ]
            )
        )


@pytest.mark.unit
def test_default_routing_without_rules_rejected() -> None:
    with pytest.raises(ConfigError, match=r"default_routing.*requires routing_rules"):
        _build_alerting(_yaml_alerting(default_routing={"action": "drop", "notify": []}))


@pytest.mark.unit
def test_rule_name_rejects_non_string() -> None:
    """rule_name must be a string glob; non-strings would crash fnmatch at dispatch."""
    with pytest.raises(ConfigError, match="rule_name must be a string glob"):
        _build_alerting(
            _yaml_alerting(
                routing_rules=[
                    {
                        "match": {"rule_name": 123},
                        "notify": [{"channel": "oncall-slack"}],
                    },
                ]
            )
        )


@pytest.mark.unit
def test_digest_window_minutes_capped_at_1440() -> None:
    """digest_window_minutes over one day is rejected to bound buffer growth."""
    with pytest.raises(ConfigError, match=r"digest_window_minutes must be int in \[1, 1440\]"):
        _build_alerting(
            _yaml_alerting(
                routing_rules=[
                    {
                        "match": {},
                        "notify": [
                            {
                                "channel": "oncall-slack",
                                "mode": "digest",
                                "digest_window_minutes": 1441,
                            }
                        ],
                    },
                ]
            )
        )


@pytest.mark.unit
def test_default_routing_notify_requires_non_empty_list() -> None:
    with pytest.raises(ConfigError, match=r"action=notify requires a non-empty notify list"):
        _build_alerting(
            _yaml_alerting(
                routing_rules=[
                    {"match": {}, "notify": [{"channel": "oncall-slack"}]},
                ],
                default_routing={"action": "notify", "notify": []},
            )
        )


@pytest.mark.unit
def test_quiet_hours_end_equal_start_rejected() -> None:
    with pytest.raises(ConfigError, match="end must differ from start"):
        _build_alerting(
            {
                "webhooks": [
                    {
                        "name": "x",
                        "url": "https://x/h",
                        "format": "json",
                        "quiet_hours": {
                            "start": "22:00",
                            "end": "22:00",
                            "min_severity": 5,
                        },
                    }
                ],
            }
        )


@pytest.mark.unit
def test_webhook_name_auto_defaults() -> None:
    cfg = _build_alerting(
        {
            "webhooks": [
                {"url": "https://a/h", "format": "json"},
                {"url": "https://b/h", "format": "json"},
            ]
        }
    )
    assert [t.name for t in cfg.webhook_targets] == ["webhook-0", "webhook-1"]


@pytest.mark.unit
def test_webhook_name_collision_rejected() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        _build_alerting(
            {
                "webhooks": [
                    {"name": "x", "url": "https://a/h", "format": "json"},
                    {"name": "x", "url": "https://b/h", "format": "json"},
                ]
            }
        )


@pytest.mark.unit
def test_invalid_severity_bounds_rejected() -> None:
    with pytest.raises(ConfigError, match=r"min_severity.*max_severity"):
        _build_alerting(
            _yaml_alerting(
                routing_rules=[
                    {
                        "match": {"min_severity": 6, "max_severity": 3},
                        "notify": [{"channel": "oncall-slack"}],
                    }
                ]
            )
        )
