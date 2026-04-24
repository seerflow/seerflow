"""Rate limiting + CORS helpers for the Seerflow REST API (S-181).

This module owns:

* the module-level ``slowapi.Limiter`` placeholder used by route decorators
* the per-request key function (``_key_func``)
* the configurable limit-string closures (``list_limit`` / ``detail_limit``)
* the CORS allowlist resolver (``resolve_allowed_origins``)
* the per-app ``Limiter`` reconfiguration (``configure_limiter``)

Routes decorate with ``@limiter.limit(list_limit)`` or
``@limiter.limit(detail_limit)``; at request time, ``SlowAPIMiddleware``
resolves to ``request.app.state.limiter`` (built per-app from config by
``_install_security_middlewares`` in ``seerflow.api.app``), so the
module-level ``limiter`` is kept disabled to avoid accidental throttling
during decoration.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.util import get_remote_address

from seerflow.config import ConfigError, SeerflowConfig

if TYPE_CHECKING:
    from starlette.requests import Request


def _is_public_ip(value: str) -> bool:
    """Return True iff *value* is a valid, globally routable IP.

    Rejects loopback, link-local, multicast, and RFC-1918 private
    ranges. A client that submits a spoofed ``X-Forwarded-For`` entry
    pointing at 127.0.0.1 or 10.x.y.z would otherwise end up sharing
    a bucket with local/private traffic, bypassing per-IP throttling.
    """
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast)


def _key_func(request: Request) -> str:
    """Return the rate limit bucket identifier for *request*.

    When ``api_trust_proxy_headers`` is True on the app's config, the
    left-most ``X-Forwarded-For`` hop is used **provided** it is a
    globally routable IP. A client-supplied private or loopback
    address falls back to the direct client host to prevent
    bucket-sharing attacks. Operators opt in explicitly because
    ``X-Forwarded-For`` is trivially spoofable when the proxy does not
    sanitise the header.
    """
    config: SeerflowConfig | None = getattr(request.app.state, "config", None)
    if config is not None and config.api_trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            candidate = xff.split(",", 1)[0].strip()
            if _is_public_ip(candidate):
                return candidate
    return get_remote_address(request)


def _default_localhost_origins(dashboard_port: int) -> tuple[str, str]:
    """Return the two-element localhost fallback origin tuple."""
    return (
        f"http://localhost:{dashboard_port}",
        f"http://127.0.0.1:{dashboard_port}",
    )


def resolve_allowed_origins(config: SeerflowConfig | None) -> tuple[str, ...]:
    """Resolve the CORS allowlist via a fallback chain.

    Priority: ``api_allowed_origins`` → ``ws_allowed_origins`` →
    localhost origins derived from ``dashboard_port``. Returns an empty
    tuple when ``config`` is ``None`` (test harness — caller skips CORS
    middleware).
    """
    if config is None:
        return ()
    if config.api_allowed_origins:
        return config.api_allowed_origins
    if config.ws_allowed_origins:
        return config.ws_allowed_origins
    return _default_localhost_origins(config.dashboard_port)


def configure_limiter(config: SeerflowConfig) -> None:
    """Configure the module-level ``limiter`` for the current app.

    Route decorators capture the module-level ``limiter`` singleton at
    import time. To allow per-app config changes (enable/disable,
    Redis URI, key function), we mutate the singleton rather than
    creating a disconnected instance that would never be consulted by
    the middleware.

    Raises :class:`ConfigError` if ``api_rate_limit_redis_url`` is set
    but the ``redis`` package is not installed.
    """
    if config.api_rate_limit_redis_url:
        try:
            import redis  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "api_rate_limit_redis_url is set but the 'redis' package "
                "is not installed. Install with: pip install 'seerflow[redis]'"
            ) from exc
        storage_uri = config.api_rate_limit_redis_url
    else:
        storage_uri = "memory://"

    # Rebuild internal storage + rate-limit engine so repeated calls in
    # the same process (tests) do not leak counters between apps.
    fresh = Limiter(
        key_func=_key_func,
        storage_uri=storage_uri,
        enabled=config.api_rate_limit_enabled,
    )
    limiter.enabled = config.api_rate_limit_enabled
    limiter._storage = fresh._storage
    limiter._limiter = fresh._limiter

    global _current_list_limit, _current_detail_limit, _current_coverage_limit
    _current_list_limit = config.api_list_rate_limit
    _current_detail_limit = config.api_detail_rate_limit
    _current_coverage_limit = config.api_coverage_rate_limit


# Module-level limit strings. ``slowapi.Limiter.limit`` accepts a
# zero-arg callable that returns the limit string per request, so
# routes decorate with ``@limiter.limit(list_limit)`` and the callable
# reads the current config-driven value at request time. A single
# module slot is fine because only one ``SeerflowConfig`` is active
# per process (single-tenant service).
_DEFAULTS = SeerflowConfig()
_current_list_limit = _DEFAULTS.api_list_rate_limit
_current_detail_limit = _DEFAULTS.api_detail_rate_limit
_current_coverage_limit = _DEFAULTS.api_coverage_rate_limit


def list_limit() -> str:
    """Return the current list-endpoint rate limit string."""
    return _current_list_limit


def detail_limit() -> str:
    """Return the current detail-endpoint rate limit string."""
    return _current_detail_limit


def coverage_limit() -> str:
    """Return the current coverage-endpoint rate limit string."""
    return _current_coverage_limit


def sigma_upload_limit() -> str:
    """Return the rate limit for ``POST /api/v1/sigma/rules`` (S-151).

    Stricter than ``list_limit`` to bound disk-fill / DoS via uploads.
    Hardcoded for now; expose via ``SeerflowConfig`` if operator demand surfaces.
    """
    return "5/minute"


# Module-level singleton — slowapi decorator target. ``configure_limiter``
# rebinds its storage and enabled flag based on the active app's
# ``SeerflowConfig``. Starts disabled so that a route imported in
# isolation (e.g., during direct unit-test of a handler) does not
# throttle.
limiter = Limiter(key_func=_key_func, enabled=False)
