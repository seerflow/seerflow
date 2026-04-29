"""TAXII / threat-intelligence section builders for seerflow config.

Imports ``ConfigError`` from ``seerflow._config_validation`` (leaf) and the
threat-intel dataclasses from ``seerflow.config``. ``_walk_and_interpolate``
is loaded lazily inside ``build_seerflow_config`` to avoid the
``seerflow.config`` ↔ ``seerflow._config_builders`` import cycle when this
module is the entry point. Used by ``seerflow.config.load_config`` and
re-exported by ``seerflow._config_builders`` for legacy callers (notably
``tests/unit/test_threat_intel_config_loading.py``).

Extracted from ``seerflow._config_builders`` in S-226 to keep that module
under CLAUDE.md's 800-line file ceiling.
"""

from __future__ import annotations

from typing import Any

from seerflow._config_validation import ConfigError
from seerflow.config import (
    IoCMatcherConfig,
    SeerflowConfig,
    TAXIIAuthConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)


def _build_taxii_auth_config(data: dict[str, Any]) -> TAXIIAuthConfig:
    """Build a TAXIIAuthConfig from a raw mapping. Caller verifies non-None."""
    kind_raw = data.get("kind")
    if kind_raw not in ("api_key", "basic"):
        raise ConfigError(
            f"threat_intel.feeds[].auth.kind must be 'api_key' or 'basic', got {kind_raw!r}"
        )
    api_key_env = data.get("api_key_env")
    if api_key_env is not None and not isinstance(api_key_env, str):
        raise ConfigError("threat_intel.feeds[].auth.api_key_env must be a string or omitted")
    api_key_header = data.get("api_key_header", "Authorization")
    if not isinstance(api_key_header, str) or not api_key_header:
        raise ConfigError("threat_intel.feeds[].auth.api_key_header must be a non-empty string")
    username_env = data.get("username_env")
    if username_env is not None and not isinstance(username_env, str):
        raise ConfigError("threat_intel.feeds[].auth.username_env must be a string or omitted")
    password_env = data.get("password_env")
    if password_env is not None and not isinstance(password_env, str):
        raise ConfigError("threat_intel.feeds[].auth.password_env must be a string or omitted")
    return TAXIIAuthConfig(
        kind=kind_raw,
        api_key_env=api_key_env,
        api_key_header=api_key_header,
        username_env=username_env,
        password_env=password_env,
    )


def _build_taxii_feed_config(data: dict[str, Any]) -> TAXIIFeedConfig:
    """Build one TAXIIFeedConfig from a raw mapping."""
    if not isinstance(data, dict):
        raise ConfigError(
            f"threat_intel.feeds[] entries must be mappings, got {type(data).__name__}"
        )
    return TAXIIFeedConfig(
        id=_require_taxii_str(data, "id"),
        url=_require_taxii_str(data, "url"),
        collection_id=_require_taxii_str(data, "collection_id"),
        poll_interval_s=_require_taxii_optional_int(data, "poll_interval_s"),
        auth=_require_taxii_auth(data),
        confidence_floor=_require_taxii_int(data, "confidence_floor", default=0),
        enabled=_require_taxii_bool(data, "enabled", default=True),
        allow_insecure=_require_taxii_bool(data, "allow_insecure", default=False),
        allow_private_addresses=_require_taxii_bool(
            data, "allow_private_addresses", default=False
        ),
    )


def _require_taxii_str(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"threat_intel.feeds[].{field} must be a non-empty string")
    return value


def _require_taxii_int(data: dict[str, Any], field: str, *, default: int) -> int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"threat_intel.feeds[].{field} must be an int, got {type(value).__name__}"
        )
    return int(value)


def _require_taxii_optional_int(data: dict[str, Any], field: str) -> int | None:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"threat_intel.feeds[].{field} must be an int or omitted, got {type(value).__name__}"
        )
    return int(value)


def _require_taxii_bool(data: dict[str, Any], field: str, *, default: bool) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ConfigError(f"threat_intel.feeds[].{field} must be a bool")
    return value


def _require_taxii_auth(data: dict[str, Any]) -> TAXIIAuthConfig | None:
    auth_raw = data.get("auth")
    if auth_raw is None:
        return None
    if not isinstance(auth_raw, dict):
        raise ConfigError(
            "threat_intel.feeds[].auth must be a mapping or omitted, "
            f"got {type(auth_raw).__name__}"
        )
    return _build_taxii_auth_config(auth_raw)


def _build_ioc_matcher_config(data: dict[str, Any]) -> IoCMatcherConfig:
    """Build the IoC matcher block. Empty / missing returns defaults."""
    if not data:
        return IoCMatcherConfig()
    if not isinstance(data, dict):
        raise ConfigError(f"threat_intel.matcher must be a mapping, got {type(data).__name__}")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("threat_intel.matcher.enabled must be a bool")

    fpr = data.get("fpr", 0.001)
    if isinstance(fpr, bool) or not isinstance(fpr, int | float):
        raise ConfigError("threat_intel.matcher.fpr must be a number")

    min_capacity = data.get("min_capacity", 100_000)
    if isinstance(min_capacity, bool) or not isinstance(min_capacity, int):
        raise ConfigError("threat_intel.matcher.min_capacity must be an int")

    growth = data.get("capacity_growth_factor", 1.25)
    if isinstance(growth, bool) or not isinstance(growth, int | float):
        raise ConfigError("threat_intel.matcher.capacity_growth_factor must be a number")

    confidence_floor = data.get("confidence_floor", 0)
    if isinstance(confidence_floor, bool) or not isinstance(confidence_floor, int):
        raise ConfigError("threat_intel.matcher.confidence_floor must be an int")

    debounce = data.get("rebuild_debounce_ms", 200)
    if isinstance(debounce, bool) or not isinstance(debounce, int):
        raise ConfigError("threat_intel.matcher.rebuild_debounce_ms must be an int")

    enabled_types_raw = data.get(
        "enabled_types",
        ("ipv4", "ipv6", "domain", "url", "md5", "sha1", "sha256"),
    )
    if not isinstance(enabled_types_raw, list | tuple):
        raise ConfigError("threat_intel.matcher.enabled_types must be a list of strings")
    enabled_types = tuple(str(t) for t in enabled_types_raw)

    return IoCMatcherConfig(
        enabled=enabled,
        fpr=float(fpr),
        min_capacity=min_capacity,
        capacity_growth_factor=float(growth),
        confidence_floor=confidence_floor,
        rebuild_debounce_ms=debounce,
        enabled_types=enabled_types,
    )


def _build_threat_intel_config(data: dict[str, Any]) -> ThreatIntelConfig:
    """Build the threat-intelligence section. Missing key returns defaults."""
    if not data:
        return ThreatIntelConfig()
    if not isinstance(data, dict):
        raise ConfigError(f"threat_intel must be a mapping, got {type(data).__name__}")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("threat_intel.enabled must be a bool")

    feeds_raw = data.get("feeds", ())
    if feeds_raw is None:
        feeds_raw = ()
    if not isinstance(feeds_raw, list | tuple):
        raise ConfigError(f"threat_intel.feeds must be a list, got {type(feeds_raw).__name__}")
    feeds = tuple(_build_taxii_feed_config(entry) for entry in feeds_raw)

    default_poll = data.get("default_poll_interval_s", 3600)
    if isinstance(default_poll, bool) or not isinstance(default_poll, int):
        raise ConfigError("threat_intel.default_poll_interval_s must be an int")

    request_timeout = data.get("request_timeout_s", 30.0)
    if isinstance(request_timeout, bool) or not isinstance(request_timeout, int | float):
        raise ConfigError("threat_intel.request_timeout_s must be a number")

    max_indicators = data.get("max_indicators_per_feed", 1_000_000)
    if isinstance(max_indicators, bool) or not isinstance(max_indicators, int):
        raise ConfigError("threat_intel.max_indicators_per_feed must be an int")

    expired_grace = data.get("expired_grace_days", 30)
    if isinstance(expired_grace, bool) or not isinstance(expired_grace, int):
        raise ConfigError("threat_intel.expired_grace_days must be an int")

    startup_jitter = data.get("startup_jitter_s", 30)
    if isinstance(startup_jitter, bool) or not isinstance(startup_jitter, int):
        raise ConfigError("threat_intel.startup_jitter_s must be an int")

    matcher_raw = data.get("matcher", {})
    matcher = _build_ioc_matcher_config(matcher_raw)

    return ThreatIntelConfig(
        enabled=enabled,
        feeds=feeds,
        default_poll_interval_s=default_poll,
        request_timeout_s=float(request_timeout),
        max_indicators_per_feed=max_indicators,
        expired_grace_days=expired_grace,
        startup_jitter_s=startup_jitter,
        matcher=matcher,
    )


def build_seerflow_config(raw: dict[str, Any]) -> SeerflowConfig:
    """Build a SeerflowConfig from an in-memory raw mapping.

    Lightweight wrapper used by the threat-intel test surface (S-067). Mirrors
    the subset of behaviour that tests rely on: section builders applied with
    sensible defaults and env-var interpolation. Heavier validation lives in
    ``validate_seerflow_config`` so callers can opt-in.
    """
    # Deferred to avoid the seerflow.config ↔ _config_builders import cycle
    # when _threat_intel_builders is loaded as the entry point.
    from seerflow._config_builders import _walk_and_interpolate

    interpolated = _walk_and_interpolate(raw or {})
    return SeerflowConfig(
        threat_intel=_build_threat_intel_config(interpolated.get("threat_intel", {})),
    )
