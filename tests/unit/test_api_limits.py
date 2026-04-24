"""Unit tests for seerflow.api.limits (S-181)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from seerflow.api.limits import (
    _key_func,
    configure_limiter,
    detail_limit,
    resolve_allowed_origins,
)
from seerflow.api.limits import list_limit as list_limit_fn
from seerflow.config import ConfigError, SeerflowConfig


def _request(
    *,
    client_host: str = "10.0.0.1",
    xff: str | None = None,
    config: SeerflowConfig | None = None,
) -> MagicMock:
    req = MagicMock()
    req.client.host = client_host
    req.headers = {"x-forwarded-for": xff} if xff is not None else {}
    req.app.state.config = config
    return req


class TestKeyFunc:
    def test_uses_client_host_when_trust_proxy_disabled(self) -> None:
        cfg = SeerflowConfig(api_trust_proxy_headers=False)
        req = _request(client_host="10.0.0.1", xff="1.2.3.4", config=cfg)
        assert _key_func(req) == "10.0.0.1"

    def test_uses_xff_first_hop_when_trust_proxy_enabled(self) -> None:
        cfg = SeerflowConfig(api_trust_proxy_headers=True)
        req = _request(
            client_host="10.0.0.1",
            xff="8.8.8.8, 1.1.1.1",
            config=cfg,
        )
        assert _key_func(req) == "8.8.8.8"

    def test_rejects_loopback_xff_to_prevent_bucket_sharing(self) -> None:
        """Security: spoofed XFF=127.0.0.1 falls back to client.host."""
        cfg = SeerflowConfig(api_trust_proxy_headers=True)
        req = _request(client_host="203.0.113.1", xff="127.0.0.1", config=cfg)
        assert _key_func(req) == "203.0.113.1"

    def test_rejects_private_xff_to_prevent_bucket_sharing(self) -> None:
        """Security: spoofed RFC1918 XFF falls back to client.host."""
        cfg = SeerflowConfig(api_trust_proxy_headers=True)
        req = _request(client_host="203.0.113.1", xff="10.0.0.5", config=cfg)
        assert _key_func(req) == "203.0.113.1"

    def test_rejects_garbage_xff(self) -> None:
        cfg = SeerflowConfig(api_trust_proxy_headers=True)
        req = _request(client_host="203.0.113.1", xff="not-an-ip", config=cfg)
        assert _key_func(req) == "203.0.113.1"

    def test_falls_back_to_client_when_xff_missing(self) -> None:
        cfg = SeerflowConfig(api_trust_proxy_headers=True)
        req = _request(client_host="10.0.0.1", xff=None, config=cfg)
        assert _key_func(req) == "10.0.0.1"

    def test_handles_missing_config(self) -> None:
        req = _request(client_host="10.0.0.1", config=None)
        assert _key_func(req) == "10.0.0.1"


class TestResolveAllowedOrigins:
    def test_prefers_api_field(self) -> None:
        cfg = SeerflowConfig(
            api_allowed_origins=("https://dash.example.com",),
            ws_allowed_origins=("https://ws.example.com",),
            dashboard_port=8080,
        )
        assert resolve_allowed_origins(cfg) == ("https://dash.example.com",)

    def test_falls_back_to_ws(self) -> None:
        cfg = SeerflowConfig(
            api_allowed_origins=(),
            ws_allowed_origins=("https://ws.example.com",),
            dashboard_port=8080,
        )
        assert resolve_allowed_origins(cfg) == ("https://ws.example.com",)

    def test_falls_back_to_dashboard_port(self) -> None:
        cfg = SeerflowConfig(
            api_allowed_origins=(),
            ws_allowed_origins=(),
            dashboard_port=4000,
        )
        result = resolve_allowed_origins(cfg)
        assert set(result) == {
            "http://localhost:4000",
            "http://127.0.0.1:4000",
        }

    def test_empty_when_no_config(self) -> None:
        assert resolve_allowed_origins(None) == ()


class TestBuildLimiter:
    def test_in_memory_when_no_redis_url(self) -> None:
        from seerflow.api.limits import limiter as _limiter

        configure_limiter(SeerflowConfig(api_rate_limit_redis_url=None))
        assert _limiter.enabled is True

    def test_respects_enabled_false(self) -> None:
        from seerflow.api.limits import limiter as _limiter

        configure_limiter(SeerflowConfig(api_rate_limit_enabled=False))
        assert _limiter.enabled is False

    def test_raises_when_redis_url_set_and_pkg_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "redis", None)
        cfg = SeerflowConfig(api_rate_limit_redis_url="redis://localhost:6379/0")
        with pytest.raises(ConfigError, match=r"seerflow\[redis\]"):
            configure_limiter(cfg)


class TestLimitClosures:
    def test_configure_limiter_applies_list_limit(self) -> None:
        configure_limiter(SeerflowConfig(api_list_rate_limit="7/minute"))
        assert list_limit_fn() == "7/minute"

    def test_configure_limiter_applies_detail_limit(self) -> None:
        configure_limiter(SeerflowConfig(api_detail_rate_limit="11/minute"))
        assert detail_limit() == "11/minute"

    def test_default_closures_return_config_defaults(self) -> None:
        configure_limiter(SeerflowConfig())
        defaults = SeerflowConfig()
        assert list_limit_fn() == defaults.api_list_rate_limit
        assert detail_limit() == defaults.api_detail_rate_limit


class TestRebindLimiterInternals:
    """S-185: the single helper that touches slowapi private attributes."""

    def test_swaps_storage_and_limiter_references(self) -> None:
        from slowapi import Limiter

        from seerflow.api.limits import _rebind_limiter_internals

        old = Limiter(key_func=_key_func, storage_uri="memory://", enabled=False)
        new = Limiter(key_func=_key_func, storage_uri="memory://", enabled=True)

        _rebind_limiter_internals(old, new)

        assert old._storage is new._storage
        assert old._limiter is new._limiter

    def test_raises_attribute_error_with_loud_log_if_storage_removed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from slowapi import Limiter

        from seerflow.api.limits import _rebind_limiter_internals

        old = Limiter(key_func=_key_func, storage_uri="memory://", enabled=False)
        new = Limiter(key_func=_key_func, storage_uri="memory://", enabled=True)

        del new._storage

        with (
            caplog.at_level(logging.ERROR, logger="seerflow.api.limits"),
            pytest.raises(AttributeError, match="_storage"),
        ):
            _rebind_limiter_internals(old, new)

        assert any(
            "slowapi.Limiter is missing private attribute" in record.message
            for record in caplog.records
        )
