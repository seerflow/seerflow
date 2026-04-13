"""Tests for api.routes.config — redact_config helper and endpoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seerflow.alerting.dispatcher import WebhookTarget
from seerflow.api.routes.config import redact_config
from seerflow.config import (
    AlertingConfig,
    ReceiverConfig,
    SeerflowConfig,
    StorageConfig,
    WebhookEndpointConfig,
)


class TestRedactConfig:
    def test_postgresql_url_masked_when_set(self) -> None:
        cfg = SeerflowConfig(
            storage=StorageConfig(
                backend="postgresql",
                postgresql_url="postgres://user:PASSWORD@host:5432/db",
            )
        )
        data = redact_config(cfg)
        assert data["storage"]["postgresql_url"] == "***"

    def test_postgresql_url_empty_stays_empty(self) -> None:
        cfg = SeerflowConfig()
        data = redact_config(cfg)
        assert data["storage"]["postgresql_url"] == ""

    def test_pagerduty_routing_key_masked(self) -> None:
        cfg = SeerflowConfig(
            alerting=AlertingConfig(pagerduty_routing_key="secret-key-xyz")
        )
        data = redact_config(cfg)
        assert data["alerting"]["pagerduty_routing_key"] == "***"

    def test_pagerduty_empty_stays_empty(self) -> None:
        cfg = SeerflowConfig()
        data = redact_config(cfg)
        assert data["alerting"]["pagerduty_routing_key"] == ""

    def test_webhook_target_url_masked(self) -> None:
        target = WebhookTarget(
            url="https://hooks.slack.com/services/T123/B456/SECRET",
            format="slack",
            min_severity=3,
        )
        cfg = SeerflowConfig(
            alerting=AlertingConfig(webhook_targets=(target,))
        )
        data = redact_config(cfg)
        assert data["alerting"]["webhook_targets"][0]["url"] == "https://hooks.slack.com/***"
        assert data["alerting"]["webhook_targets"][0]["format"] == "slack"

    def test_receiver_webhook_auth_token_masked(self) -> None:
        wh = WebhookEndpointConfig(
            path="/ingest/webhook",
            auth_header="X-Auth-Token",
            auth_token="topsecret",
        )
        cfg = SeerflowConfig(receivers=ReceiverConfig(webhooks=(wh,)))
        data = redact_config(cfg)
        assert data["receivers"]["webhooks"][0]["auth_token"] == "***"
        assert data["receivers"]["webhooks"][0]["auth_header"] == "X-Auth-Token"

    def test_non_secret_fields_preserved(self) -> None:
        cfg = SeerflowConfig(
            storage=StorageConfig(
                backend="sqlite",
                data_dir="/data/seerflow",
                sqlite_path="/data/seerflow/db.sqlite",
            ),
            dashboard_port=9090,
            log_level="DEBUG",
        )
        data = redact_config(cfg)
        assert data["storage"]["backend"] == "sqlite"
        assert data["storage"]["data_dir"] == "/data/seerflow"
        assert data["storage"]["sqlite_path"] == "/data/seerflow/db.sqlite"
        assert data["dashboard_port"] == 9090
        assert data["log_level"] == "DEBUG"

    def test_returns_new_dict_does_not_mutate_config(self) -> None:
        cfg = SeerflowConfig(
            alerting=AlertingConfig(pagerduty_routing_key="actual-key")
        )
        data = redact_config(cfg)
        assert cfg.alerting.pagerduty_routing_key == "actual-key"
        assert data["alerting"]["pagerduty_routing_key"] == "***"
