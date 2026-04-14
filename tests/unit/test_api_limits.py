"""Unit tests for seerflow.api.limits (S-181)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from seerflow.api.limits import (
    _key_func,
    build_limiter,
    detail_limit,
    resolve_allowed_origins,
)
from seerflow.config import ConfigError, SeerflowConfig
from seerflow.api.limits import list_limit as list_limit_fn


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
            xff="203.0.113.5, 198.51.100.1",
            config=cfg,
        )
        assert _key_func(req) == "203.0.113.5"

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
        cfg = SeerflowConfig(api_rate_limit_redis_url=None)
        limiter = build_limiter(cfg)
        assert limiter is not None
        assert limiter.enabled is True

    def test_respects_enabled_false(self) -> None:
        cfg = SeerflowConfig(api_rate_limit_enabled=False)
        limiter = build_limiter(cfg)
        assert limiter.enabled is False

    def test_raises_when_redis_url_set_and_pkg_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "redis", None)
        cfg = SeerflowConfig(api_rate_limit_redis_url="redis://localhost:6379/0")
        with pytest.raises(ConfigError, match=r"seerflow\[redis\]"):
            build_limiter(cfg)


class TestLimitClosures:
    def test_list_limit_reads_from_app_state(self) -> None:
        cfg = SeerflowConfig(api_list_rate_limit="7/minute")
        req = _request(config=cfg)
        assert list_limit_fn(req) == "7/minute"

    def test_detail_limit_reads_from_app_state(self) -> None:
        cfg = SeerflowConfig(api_detail_rate_limit="11/minute")
        req = _request(config=cfg)
        assert detail_limit(req) == "11/minute"

    def test_list_limit_falls_back_to_default_when_no_config(self) -> None:
        req = _request(config=None)
        assert list_limit_fn(req) == SeerflowConfig().api_list_rate_limit

    def test_detail_limit_falls_back_to_default_when_no_config(self) -> None:
        req = _request(config=None)
        assert detail_limit(req) == SeerflowConfig().api_detail_rate_limit
