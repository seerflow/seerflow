"""Branch coverage tests for TAXIIFeedManager and ``_resolve_auth`` (S-067).

Targets the missing branches identified in coverage:
- ``metrics`` property accessor (line 46).
- ``start()`` ``RuntimeError`` from ``_build_consumer`` -> failed list (61-64).
- ``_resolve_auth`` for all kinds (None, api_key happy/missing/non-default header,
  basic happy/missing, unknown).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import TAXIIAuthConfig, TAXIIFeedConfig, ThreatIntelConfig
from seerflow.threat_intel.manager import TAXIIFeedManager, _resolve_auth
from seerflow.threat_intel.metrics import TAXIIMetricsRegistry


@pytest.fixture(autouse=True)
def _bypass_dns_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-227: bypass the startup DNS guard for tests that fabricate stub
    hostnames (``bad.example`` / ``good.example``)."""
    monkeypatch.setattr(
        "seerflow.threat_intel.dns._resolve_feed_with_private_ip_guard",
        lambda _feed_id, _hostname: "1.1.1.1",
    )


async def test_manager_exposes_metrics_property() -> None:
    cfg = ThreatIntelConfig(enabled=False)
    mgr = TAXIIFeedManager(config=cfg, model_store=MagicMock())
    assert isinstance(mgr.metrics, TAXIIMetricsRegistry)


async def test_manager_records_failed_feed_when_auth_construction_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feed configured with api_key auth but no env var -> RuntimeError on
    ``_build_consumer`` -> caught, feed id appended to failed list."""
    cfg = ThreatIntelConfig(
        enabled=True,
        startup_jitter_s=0,
        default_poll_interval_s=60,
        feeds=(
            TAXIIFeedConfig(
                id="bad",
                url="https://bad.example/",
                collection_id="c",
                auth=TAXIIAuthConfig(kind="api_key", api_key_env="UNSET_VAR"),
            ),
            TAXIIFeedConfig(id="good", url="https://good.example/", collection_id="c"),
        ),
    )
    monkeypatch.delenv("UNSET_VAR", raising=False)
    store = MagicMock()
    store.save_state = AsyncMock()
    store.load_state = AsyncMock(return_value=None)
    mgr = TAXIIFeedManager(config=cfg, model_store=store)
    failed = await mgr.start()
    try:
        assert failed == ["bad"]
        assert mgr.feed_ids() == ("good",)
    finally:
        await mgr.stop()


def test_resolve_auth_returns_none_when_auth_is_none() -> None:
    assert _resolve_auth(None) == (None, None)


def test_resolve_auth_api_key_with_authorization_header_adds_bearer_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAXII_TOKEN", "s3cret")
    auth = TAXIIAuthConfig(
        kind="api_key",
        api_key_env="TAXII_TOKEN",
        api_key_header="Authorization",
    )
    header, basic = _resolve_auth(auth)
    assert header == {"Authorization": "Bearer s3cret"}
    assert basic is None


def test_resolve_auth_api_key_with_custom_header_no_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAXII_TOKEN", "s3cret")
    auth = TAXIIAuthConfig(
        kind="api_key",
        api_key_env="TAXII_TOKEN",
        api_key_header="X-API-Key",
    )
    header, basic = _resolve_auth(auth)
    assert header == {"X-API-Key": "s3cret"}
    assert basic is None


def test_resolve_auth_api_key_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    auth = TAXIIAuthConfig(kind="api_key", api_key_env="MISSING_TOKEN")
    with pytest.raises(RuntimeError, match="MISSING_TOKEN"):
        _resolve_auth(auth)


def test_resolve_auth_api_key_no_env_field_raises() -> None:
    auth = TAXIIAuthConfig(kind="api_key", api_key_env=None)
    with pytest.raises(RuntimeError, match="api_key_env"):
        _resolve_auth(auth)


def test_resolve_auth_basic_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAXII_USER", "alice")
    monkeypatch.setenv("TAXII_PASS", "wonderland")
    auth = TAXIIAuthConfig(
        kind="basic",
        username_env="TAXII_USER",
        password_env="TAXII_PASS",
    )
    header, basic = _resolve_auth(auth)
    assert header is None
    assert basic is not None
    assert basic.login == "alice"
    assert basic.password == "wonderland"


def test_resolve_auth_basic_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TAXII_USER", "alice")
    monkeypatch.delenv("TAXII_PASS", raising=False)
    auth = TAXIIAuthConfig(
        kind="basic",
        username_env="TAXII_USER",
        password_env="TAXII_PASS",
    )
    with pytest.raises(RuntimeError, match="TAXII_USER/TAXII_PASS"):
        _resolve_auth(auth)


def test_resolve_auth_basic_no_env_fields_raises() -> None:
    auth = TAXIIAuthConfig(kind="basic", username_env=None, password_env=None)
    with pytest.raises(RuntimeError, match="username_env and password_env"):
        _resolve_auth(auth)


def test_resolve_auth_unknown_kind_raises() -> None:
    """Cover the ``case _:`` fallback in ``_resolve_auth``. ``Literal`` makes
    valid kinds 'api_key' / 'basic'; we bypass type checking via ``cast``
    to drive the unknown-kind path that the match statement guards.
    """
    from typing import cast

    auth = cast("TAXIIAuthConfig", TAXIIAuthConfig.__new__(TAXIIAuthConfig))
    object.__setattr__(auth, "kind", "weird")
    object.__setattr__(auth, "api_key_env", None)
    object.__setattr__(auth, "api_key_header", "Authorization")
    object.__setattr__(auth, "username_env", None)
    object.__setattr__(auth, "password_env", None)
    with pytest.raises(RuntimeError, match="unknown auth kind"):
        _resolve_auth(auth)


async def test_manager_double_start_raises() -> None:
    """``start()`` must reject re-entry while already running so the prior
    ``ClientSession`` is not orphaned.
    """
    cfg = ThreatIntelConfig(enabled=True, startup_jitter_s=0)
    store = MagicMock()
    store.save_state = AsyncMock()
    store.load_state = AsyncMock(return_value=None)
    mgr = TAXIIFeedManager(config=cfg, model_store=store)
    try:
        await mgr.start()
        with pytest.raises(RuntimeError, match="already running"):
            await mgr.start()
    finally:
        await mgr.stop()


async def test_build_consumer_without_start_raises() -> None:
    """Direct ``_build_consumer`` call before ``start()`` must raise the
    explicit RuntimeError instead of crashing on ``None.session``.
    """
    cfg = ThreatIntelConfig(enabled=True)
    mgr = TAXIIFeedManager(config=cfg, model_store=MagicMock())
    feed = TAXIIFeedConfig(id="x", url="https://x.example/", collection_id="c")
    with pytest.raises(RuntimeError, match="before start"):
        mgr._build_consumer(feed)
