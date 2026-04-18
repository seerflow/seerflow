"""Tests for api.routes.config — redact_config helper and endpoint."""

from __future__ import annotations

from typing import Any, ClassVar

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
        cfg = SeerflowConfig(alerting=AlertingConfig(pagerduty_routing_key="secret-key-xyz"))
        data = redact_config(cfg)
        assert data["alerting"]["pagerduty_routing_key"] == "***"

    def test_pagerduty_empty_stays_empty(self) -> None:
        cfg = SeerflowConfig()
        data = redact_config(cfg)
        assert data["alerting"]["pagerduty_routing_key"] == ""

    def test_api_rate_limit_redis_url_masked_when_set(self) -> None:
        cfg = SeerflowConfig(api_rate_limit_redis_url="redis://:SECRET@redis.internal:6379/0")
        data = redact_config(cfg)
        assert data["api_rate_limit_redis_url"] == "***"
        assert "SECRET" not in str(data)

    def test_api_rate_limit_redis_url_none_stays_none(self) -> None:
        cfg = SeerflowConfig()
        data = redact_config(cfg)
        assert data["api_rate_limit_redis_url"] is None

    def test_webhook_target_url_masked(self) -> None:
        target = WebhookTarget(
            name="slack",
            url="https://hooks.slack.com/services/T123/B456/SECRET",
            format="slack",
            min_severity=3,
        )
        cfg = SeerflowConfig(alerting=AlertingConfig(webhook_targets=(target,)))
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
        cfg = SeerflowConfig(alerting=AlertingConfig(pagerduty_routing_key="actual-key"))
        data = redact_config(cfg)
        assert cfg.alerting.pagerduty_routing_key == "actual-key"
        assert data["alerting"]["pagerduty_routing_key"] == "***"

    def test_alerting_webhooks_raw_dict_url_and_token_masked(self) -> None:
        """Cover the raw-YAML passthrough branch for alerting.webhooks."""
        cfg = SeerflowConfig(
            alerting=AlertingConfig(
                webhooks=(
                    {
                        "url": "https://hooks.example.com/services/SECRET",
                        "auth_token": "topsecret",
                        "format": "json",
                    },
                ),
            )
        )
        data = redact_config(cfg)
        wh = data["alerting"]["webhooks"][0]
        assert wh["url"] == "https://hooks.example.com/***"
        assert wh["auth_token"] == "***"
        assert wh["format"] == "json"

    def test_alerting_webhooks_raw_dict_nested_secret_masked(self) -> None:
        """Secrets under nested dicts / lists of dicts must also be scrubbed."""
        cfg = SeerflowConfig(
            alerting=AlertingConfig(
                webhooks=(
                    {
                        "url": "https://hook.example.com/a",
                        "custom_headers": {
                            "Authorization": "Bearer LEAKED",
                            "api_key": "sk-nested",
                        },
                        "targets": [
                            {"token": "leaked-in-list"},
                        ],
                    },
                ),
            )
        )
        data = redact_config(cfg)
        wh = data["alerting"]["webhooks"][0]
        # Top-level URL masked
        assert wh["url"] == "https://hook.example.com/***"
        # Nested secret key masked; non-secret key preserved
        assert wh["custom_headers"]["api_key"] == "***"
        assert wh["custom_headers"]["Authorization"] == "Bearer LEAKED"
        # Nested list of dicts — secret key masked
        assert wh["targets"][0]["token"] == "***"

    def test_alerting_webhooks_raw_dict_scrubs_all_known_secret_keys(self) -> None:
        """Guard against future raw-YAML keys (api_key, token, password, etc.)."""
        cfg = SeerflowConfig(
            alerting=AlertingConfig(
                webhooks=(
                    {
                        "url": "https://api.example.com/hook",
                        "api_key": "sk-1234567890",
                        "bearer_token": "bearer-abc",
                        "password": "hunter2",
                        "secret": "very-secret",
                        "token": "tok-xyz",
                        "format": "json",
                        "not_a_secret": "visible",
                    },
                ),
            )
        )
        data = redact_config(cfg)
        wh = data["alerting"]["webhooks"][0]
        assert wh["url"] == "https://api.example.com/***"
        assert wh["api_key"] == "***"
        assert wh["bearer_token"] == "***"
        assert wh["password"] == "***"
        assert wh["secret"] == "***"
        assert wh["token"] == "***"
        # non-secret keys preserved
        assert wh["format"] == "json"
        assert wh["not_a_secret"] == "visible"


class TestConfigEndpoint:
    def _build_app(self, config: SeerflowConfig | None) -> FastAPI:
        from seerflow.api.routes.config import router

        app = FastAPI()
        app.state.config = config
        app.include_router(router, prefix="/api/v1")
        return app

    def test_returns_redacted_config(self) -> None:
        cfg = SeerflowConfig(
            alerting=AlertingConfig(pagerduty_routing_key="secret"),
        )
        client = TestClient(self._build_app(cfg))
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerting"]["pagerduty_routing_key"] == "***"
        assert body["dashboard_port"] == 8080

    def test_returns_503_when_config_none(self) -> None:
        client = TestClient(self._build_app(None))
        resp = client.get("/api/v1/config")
        assert resp.status_code == 503
        assert "config" in resp.json()["detail"].lower()

    def test_field_order_matches_dataclass(self) -> None:
        cfg = SeerflowConfig()
        client = TestClient(self._build_app(cfg))
        resp = client.get("/api/v1/config")
        keys = list(resp.json().keys())
        expected_prefix = ["storage", "receivers", "detection", "correlation", "alerting", "llm"]
        assert keys[: len(expected_prefix)] == expected_prefix

    def test_no_secret_leaks_in_raw_body(self) -> None:
        cfg = SeerflowConfig(
            storage=StorageConfig(
                backend="postgresql",
                postgresql_url="postgres://u:CANARY_XYZ@h/d",
            ),
            alerting=AlertingConfig(pagerduty_routing_key="CANARY_PD"),
        )
        client = TestClient(self._build_app(cfg))
        resp = client.get("/api/v1/config")
        assert b"CANARY_XYZ" not in resp.content
        assert b"CANARY_PD" not in resp.content


class TestSecretRegressionGuard:
    """Force contributors to update redact_config when adding repr=False fields."""

    _EXPECTED_SECRETS: ClassVar[set[str]] = {
        "storage.postgresql_url",
        "receivers.webhooks[].auth_token",
        "alerting.pagerduty_routing_key",
        "alerting.webhook_targets[].url",
        "alerting.email_targets[].smtp_user",
        "alerting.email_targets[].smtp_password",
        "alerting.sms_targets[].auth_token",
        "alerting.telegram_targets[].bot_token",
        "alerting.whatsapp_targets[].access_token",
        "api_rate_limit_redis_url",
    }
    # Internal fields on channel targets (rate-limit buckets, circuit breakers,
    # clock injectors) that are repr=False for noise reduction, not secrecy.
    _KNOWN_PUBLIC_REPR_FALSE: ClassVar[set[str]] = {
        "alerting.sms_targets[]._bucket",
        "alerting.telegram_targets[]._bucket",
        "alerting.whatsapp_targets[]._bucket",
        "alerting.whatsapp_targets[]._circuit",
        "alerting.whatsapp_targets[]._monotonic",
    }

    def _collect_repr_false(
        self,
        cls: type,
        prefix: str = "",
    ) -> set[str]:
        import dataclasses
        import typing
        from collections.abc import Callable

        from seerflow import config as config_mod
        from seerflow.alerting.channels._ratelimit import TokenBucket
        from seerflow.alerting.channels.email import EmailTarget
        from seerflow.alerting.channels.sms import SmsTarget
        from seerflow.alerting.channels.telegram import TelegramTarget
        from seerflow.alerting.channels.whatsapp import WhatsAppTarget
        from seerflow.alerting.channels.whatsapp import _CircuitState as _WaCircuitState
        from seerflow.alerting.dispatcher import WebhookTarget
        from seerflow.alerting.router import DefaultRouting, QuietHours, RoutingRule

        # Seed localns with every dataclass defined in seerflow.config so
        # forward refs resolve. WebhookTarget is imported explicitly because
        # it lives in alerting.dispatcher but is referenced from AlertingConfig.
        # Channel targets reference TokenBucket/Callable/_CircuitState in their
        # forward refs (they are declared under ``from __future__ import
        # annotations``), so those symbols must also be resolvable.
        localns: dict[str, Any] = {
            "WebhookTarget": WebhookTarget,
            "RoutingRule": RoutingRule,
            "DefaultRouting": DefaultRouting,
            "QuietHours": QuietHours,
            "EmailTarget": EmailTarget,
            "SmsTarget": SmsTarget,
            "TelegramTarget": TelegramTarget,
            "WhatsAppTarget": WhatsAppTarget,
            "TokenBucket": TokenBucket,
            "Callable": Callable,
            "_CircuitState": _WaCircuitState,
        }
        for name in dir(config_mod):
            attr = getattr(config_mod, name)
            if isinstance(attr, type) and dataclasses.is_dataclass(attr):
                localns[name] = attr

        found: set[str] = set()
        if not dataclasses.is_dataclass(cls):
            return found
        # Fail loudly if a forward-ref cannot be resolved — silently skipping
        # would let an unredacted secret field bypass this guard.
        hints = typing.get_type_hints(cls, localns=localns)
        for f in dataclasses.fields(cls):
            path = f"{prefix}{f.name}"
            if not f.repr:
                found.add(path)
            ann = hints.get(f.name, f.type)
            args = typing.get_args(ann)
            candidates = [ann, *args]
            for c in candidates:
                if isinstance(c, type) and dataclasses.is_dataclass(c):
                    marker = f"{path}[]." if args else f"{path}."
                    found.update(self._collect_repr_false(c, prefix=marker))
        return found

    def test_every_secret_is_masked_or_allowlisted(self) -> None:
        found = self._collect_repr_false(SeerflowConfig)
        unknown = found - self._EXPECTED_SECRETS - self._KNOWN_PUBLIC_REPR_FALSE
        assert not unknown, (
            f"New repr=False field(s) detected: {sorted(unknown)}. "
            "Update redact_config() to mask them AND add to _EXPECTED_SECRETS "
            "(or _KNOWN_PUBLIC_REPR_FALSE with justification)."
        )

    def test_all_expected_secrets_still_exist(self) -> None:
        found = self._collect_repr_false(SeerflowConfig)
        missing = self._EXPECTED_SECRETS - found
        assert not missing, (
            f"Allowlisted secret(s) no longer exist: {sorted(missing)}. "
            "Remove from _EXPECTED_SECRETS."
        )
