"""Unit tests for multi-channel alerting config builders (S-163)."""

from __future__ import annotations

import pytest

from seerflow._config_builders import (
    ConfigError,
    _build_alerting,
    _build_email_targets,
    _build_sms_targets,
    _build_telegram_targets,
    _build_whatsapp_targets,
)


@pytest.mark.unit
def test_build_email_targets_happy() -> None:
    raw = (
        {
            "name": "oncall",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "use_starttls": True,
            "smtp_user": "u",
            "smtp_password": "p",
            "from_address": "alerts@x.io",
            "to_addresses": ["oncall@x.io"],
            "min_severity": 3,
        },
    )
    targets = _build_email_targets(raw)
    assert targets[0].name == "oncall"
    assert targets[0].smtp_port == 587
    assert targets[0].min_severity == 3


@pytest.mark.unit
def test_build_email_targets_rejects_private_smtp_host() -> None:
    with pytest.raises(ConfigError, match="private"):
        _build_email_targets(
            (
                {
                    "name": "x",
                    "smtp_host": "192.168.1.1",
                    "smtp_port": 25,
                    "use_starttls": False,
                    "from_address": "a@x",
                    "to_addresses": ["b@x"],
                },
            )
        )


@pytest.mark.unit
def test_build_email_targets_rejects_empty_to_addresses() -> None:
    with pytest.raises(ConfigError, match="to_addresses"):
        _build_email_targets(
            (
                {
                    "name": "x",
                    "smtp_host": "smtp.x.io",
                    "smtp_port": 587,
                    "use_starttls": True,
                    "from_address": "a@x",
                    "to_addresses": [],
                },
            )
        )


@pytest.mark.unit
def test_build_email_targets_rejects_duplicate_names() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        _build_email_targets(
            (
                {
                    "name": "dup",
                    "smtp_host": "smtp.x.io",
                    "smtp_port": 587,
                    "use_starttls": True,
                    "from_address": "a@x",
                    "to_addresses": ["b@x"],
                },
                {
                    "name": "dup",
                    "smtp_host": "smtp.x.io",
                    "smtp_port": 587,
                    "use_starttls": True,
                    "from_address": "a@x",
                    "to_addresses": ["b@x"],
                },
            )
        )


@pytest.mark.unit
def test_build_sms_targets_happy() -> None:
    raw = (
        {
            "name": "sms",
            "provider": "twilio",
            "account_sid": "AC123",
            "auth_token": "tok",
            "from_number": "+15551234567",
            "to_numbers": ["+15559876543"],
            "min_severity": 5,
        },
    )
    t = _build_sms_targets(raw)
    assert t[0].account_sid == "AC123"
    assert t[0].min_severity == 5


@pytest.mark.unit
def test_build_sms_targets_rejects_non_twilio_provider() -> None:
    with pytest.raises(ConfigError, match="twilio"):
        _build_sms_targets(
            (
                {
                    "name": "x",
                    "provider": "aws_sns",
                    "account_sid": "AC1",
                    "auth_token": "t",
                    "from_number": "+1",
                    "to_numbers": ["+2"],
                },
            )
        )


@pytest.mark.unit
def test_build_sms_targets_rejects_empty_to_numbers() -> None:
    with pytest.raises(ConfigError, match="to_numbers"):
        _build_sms_targets(
            (
                {
                    "name": "x",
                    "provider": "twilio",
                    "account_sid": "AC1",
                    "auth_token": "t",
                    "from_number": "+1",
                    "to_numbers": [],
                },
            )
        )


@pytest.mark.unit
def test_build_telegram_targets_requires_bot_token() -> None:
    with pytest.raises(ConfigError, match="bot_token"):
        _build_telegram_targets(({"name": "t", "bot_token": "", "chat_id": "-1"},))


@pytest.mark.unit
def test_build_telegram_targets_requires_chat_id() -> None:
    with pytest.raises(ConfigError, match="chat_id"):
        _build_telegram_targets(({"name": "t", "bot_token": "t:ABC", "chat_id": ""},))


@pytest.mark.unit
def test_build_whatsapp_targets_happy() -> None:
    raw = (
        {
            "name": "wa",
            "phone_number_id": "PID",
            "access_token": "tok",
            "template_name": "seerflow_alert",
            "language_code": "en",
            "to_numbers": ["+15559876543"],
        },
    )
    t = _build_whatsapp_targets(raw)
    assert t[0].phone_number_id == "PID"
    assert t[0].template_name == "seerflow_alert"


@pytest.mark.unit
def test_build_whatsapp_targets_defaults_template_name() -> None:
    raw = (
        {
            "name": "wa",
            "phone_number_id": "PID",
            "access_token": "tok",
            "to_numbers": ["+1"],
        },
    )
    t = _build_whatsapp_targets(raw)
    assert t[0].template_name == "seerflow_alert"
    assert t[0].language_code == "en"


@pytest.mark.unit
def test_alerting_config_known_channels_union_across_kinds() -> None:
    data = {
        "webhooks": [
            {"name": "wh", "url": "https://x.example", "format": "json"},
        ],
        "email_targets": [
            {
                "name": "em",
                "smtp_host": "smtp.x.io",
                "smtp_port": 587,
                "use_starttls": True,
                "from_address": "a@x",
                "to_addresses": ["b@x"],
            },
        ],
        "telegram_targets": [
            {"name": "tg", "bot_token": "t:ABC", "chat_id": "-1"},
        ],
        "routing_rules": [
            {
                "match": {},
                "notify": [
                    {"channel": "em"},
                    {"channel": "wh"},
                    {"channel": "tg"},
                ],
            },
        ],
    }
    cfg = _build_alerting(data)
    assert cfg.email_targets[0].name == "em"
    assert cfg.telegram_targets[0].name == "tg"
    assert len(cfg.routing_rules) == 1


@pytest.mark.unit
def test_alerting_config_routing_rule_rejects_unknown_channel() -> None:
    data = {
        "email_targets": [
            {
                "name": "em",
                "smtp_host": "smtp.x.io",
                "smtp_port": 587,
                "use_starttls": True,
                "from_address": "a@x",
                "to_addresses": ["b@x"],
            },
        ],
        "routing_rules": [
            {"match": {}, "notify": [{"channel": "nope"}]},
        ],
    }
    with pytest.raises(ConfigError, match="nope"):
        _build_alerting(data)


@pytest.mark.unit
def test_alerting_config_defaults_all_target_tuples_empty() -> None:
    cfg = _build_alerting({})
    assert cfg.email_targets == ()
    assert cfg.sms_targets == ()
    assert cfg.telegram_targets == ()
    assert cfg.whatsapp_targets == ()
