"""Rate limiting + CORS helpers for the Seerflow REST API (S-181).

This module owns:

* the module-level ``slowapi.Limiter`` placeholder used by route decorators
* the per-request key function (``_key_func``)
* the configurable limit-string closures (``list_limit`` / ``detail_limit``)
* the CORS allowlist resolver (``resolve_allowed_origins``)
* the per-app ``Limiter`` factory (``build_limiter``)

Routes decorate with ``@limiter.limit(list_limit)`` or
``@limiter.limit(detail_limit)``; at request time, ``SlowAPIMiddleware``
resolves to ``request.app.state.limiter`` (built per-app from config by
``_install_security_middlewares`` in ``seerflow.api.app``), so the
module-level ``limiter`` is kept disabled to avoid accidental throttling
during decoration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from slowapi import Limiter
from slowapi.util import get_remote_address

from seerflow.config import ConfigError, SeerflowConfig

if TYPE_CHECKING:
    from starlette.requests import Request


def _key_func(request: Request) -> str:
    """Return the rate limit bucket identifier for *request*.

    When ``api_trust_proxy_headers`` is True on the app's config, the
    left-most ``X-Forwarded-For`` hop is used. Otherwise falls back to
    the direct client address. Operators opt in explicitly because
    ``X-Forwarded-For`` is trivially spoofable when the proxy does not
    sanitise the header.
    """
    config: SeerflowConfig | None = getattr(request.app.state, "config", None)
    if config is not None and config.api_trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",", 1)[0].strip()
    return get_remote_address(request)


def _default_localhost_origins(dashboard_port: int) -> tuple[str, ...]:
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


def build_limiter(config: SeerflowConfig) -> Limiter:
    """Construct the ``slowapi.Limiter`` for the application.

    Uses in-memory storage by default. When
    ``config.api_rate_limit_redis_url`` is set, switches to Redis
    storage; raises :class:`ConfigError` if the ``redis`` package is
    not installed.
    """
    storage_uri = "memory://"
    if config.api_rate_limit_redis_url:
        try:
            import redis  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "api_rate_limit_redis_url is set but the 'redis' package "
                "is not installed. Install with: pip install 'seerflow[redis]'"
            ) from exc
        storage_uri = config.api_rate_limit_redis_url

    return Limiter(
        key_func=_key_func,
        storage_uri=storage_uri,
        enabled=config.api_rate_limit_enabled,
    )


def list_limit(request: Request) -> str:
    """Rate limit string for list endpoints, read from app state."""
    config: SeerflowConfig | None = getattr(request.app.state, "config", None)
    return (
        config.api_list_rate_limit
        if config is not None
        else SeerflowConfig().api_list_rate_limit
    )


def detail_limit(request: Request) -> str:
    """Rate limit string for detail endpoints, read from app state."""
    config: SeerflowConfig | None = getattr(request.app.state, "config", None)
    return (
        config.api_detail_rate_limit
        if config is not None
        else SeerflowConfig().api_detail_rate_limit
    )


# Module-level placeholder — slowapi decorator target. Per-app ``Limiter``
# is stored on ``app.state.limiter`` and resolved by ``SlowAPIMiddleware``
# at request time. Keeping this disabled prevents accidental enforcement
# outside of an app context (e.g., direct route-function unit tests).
limiter = Limiter(key_func=_key_func, enabled=False)
