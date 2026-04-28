"""Pure validation primitives + ConfigError for seerflow config.

Leaf module — no runtime imports from seerflow.*. `_validate_detection_config`
type-annotates its parameter via `TYPE_CHECKING` to avoid a runtime cycle with
`config.py`.

Extracted from `seerflow.config` in S-172 to keep config.py under CLAUDE.md's
800-line file ceiling.
"""

from __future__ import annotations

import ipaddress
import math
from typing import TYPE_CHECKING

from limits import parse as _parse_limit_string

if TYPE_CHECKING:
    from seerflow.config import (
        DetectionConfig,
        SeerflowConfig,
        TAXIIFeedConfig,
        ThreatIntelConfig,
    )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration is invalid or a required env var is missing."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_STORAGE_BACKENDS = frozenset({"sqlite", "postgresql"})

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _is_private_ip(hostname: str | None) -> bool:
    """Return True if hostname is an IP literal in a private, reserved, or CGNAT range."""
    if not hostname:
        return False
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    # Unwrap IPv6-mapped IPv4 (e.g. ::ffff:10.0.0.1) so CGNAT check works
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr in _CGNAT_NETWORK
    )


def _require_valid_port(name: str, value: int) -> None:
    if not (1 <= value <= 65535):
        raise ConfigError(f"{name} must be between 1 and 65535, got {value!r}")


def _require_finite_positive(field: str, value: float) -> None:
    """Raise ConfigError if *value* is not finite or not > 0."""
    if not math.isfinite(value) or value <= 0.0:
        raise ConfigError(f"{field} must be finite and > 0, got {value!r}")


def _require_open_unit(field: str, value: float) -> None:
    """Raise ConfigError if *value* is not in the open interval (0, 1)."""
    if not (0.0 < value < 1.0):
        raise ConfigError(f"{field} must be in (0, 1), got {value!r}")


def _is_pos_int(value: object) -> bool:
    """Return True iff ``value`` is a positive int that is not a bool."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_pos_number(value: object) -> bool:
    """Return True iff ``value`` is a positive int or float (not a bool)."""
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _validate_dashboard_url(url: str) -> None:
    """Validate dashboard_url scheme, hostname, and SSRF safety."""
    from urllib.parse import urlparse as _urlparse_url

    parsed_url = _urlparse_url(url)
    if parsed_url.scheme not in ("http", "https"):
        raise ConfigError(
            f"alerting.dashboard_url must use http or https, got {parsed_url.scheme!r}"
        )
    if not parsed_url.hostname:
        raise ConfigError("alerting.dashboard_url must include a hostname")
    if _is_private_ip(parsed_url.hostname):
        raise ConfigError(
            f"alerting.dashboard_url must not target private/reserved IP: {parsed_url.hostname}"
        )


def _validate_rate_limit_string(field_name: str, value: str) -> str:
    """Validate a ``limits``-compatible rate limit string (e.g. ``60/minute``)."""
    try:
        _parse_limit_string(value)
    except ValueError as exc:
        raise ConfigError(f"{field_name} is not a valid rate limit string: {value!r}") from exc
    return value


def _validate_detection_config(config: DetectionConfig) -> None:
    """Validate all numeric bounds in DetectionConfig; raise ConfigError if invalid."""
    # HST parameters
    if config.hst_window_size < 1:
        raise ConfigError(
            f"detection.hst_window_size must be >= 1, got {config.hst_window_size!r}"
        )
    if config.hst_n_trees < 1:
        raise ConfigError(f"detection.hst_n_trees must be >= 1, got {config.hst_n_trees!r}")

    # DSPOT parameters
    if config.dspot_calibration_window < 1:
        raise ConfigError(
            f"detection.dspot_calibration_window must be >= 1, "
            f"got {config.dspot_calibration_window!r}"
        )
    _require_open_unit("detection.dspot_risk_level", config.dspot_risk_level)
    if config.dspot_initial_percentile < 1 or config.dspot_initial_percentile > 100:
        raise ConfigError(
            f"detection.dspot_initial_percentile must be in [1, 100], "
            f"got {config.dspot_initial_percentile!r}"
        )
    if (
        not math.isfinite(config.dspot_threshold_cap_multiplier)
        or config.dspot_threshold_cap_multiplier <= 1.0
    ):
        raise ConfigError(
            f"detection.dspot_threshold_cap_multiplier must be finite and > 1.0, "
            f"got {config.dspot_threshold_cap_multiplier!r}"
        )

    # Markov parameters
    if config.markov_min_events < 1:
        raise ConfigError(
            f"detection.markov_min_events must be >= 1, got {config.markov_min_events!r}"
        )

    # Weights
    for name, value in (
        ("weights_content", config.weights_content),
        ("weights_volume", config.weights_volume),
        ("weights_sequence", config.weights_sequence),
        ("weights_pattern", config.weights_pattern),
        ("weights_template_volume", config.weights_template_volume),
        ("weights_entity_volume", config.weights_entity_volume),
    ):
        if not math.isfinite(value):
            raise ConfigError(f"detection.{name} must be finite, got {value!r}")
        if value < 0.0:
            raise ConfigError(f"detection.{name} must be >= 0.0, got {value!r}")

    if config.model_save_interval_seconds < 1:
        msg = (
            f"detection.model_save_interval_seconds must be >= 1, "
            f"got {config.model_save_interval_seconds!r}"
        )
        raise ConfigError(msg)

    if config.markov_max_entities < 1 or config.markov_max_entities > 100_000:
        msg = (
            f"detection.markov_max_entities must be between 1 and 100_000, "
            f"got {config.markov_max_entities!r}"
        )
        raise ConfigError(msg)

    if config.max_sources < 1 or config.max_sources > 10_000:
        raise ConfigError(
            f"detection.max_sources must be between 1 and 10_000, got {config.max_sources!r}"
        )

    _require_open_unit("detection.cusum_ema_alpha", config.cusum_ema_alpha)
    if config.cusum_warmup_buckets < 1:
        raise ConfigError(
            f"detection.cusum_warmup_buckets must be >= 1, got {config.cusum_warmup_buckets!r}"
        )
    _require_finite_positive("detection.cusum_drift", config.cusum_drift)
    _require_finite_positive("detection.cusum_threshold", config.cusum_threshold)

    for name in ("hw_alpha", "hw_beta", "hw_gamma"):
        _require_open_unit(f"detection.{name}", getattr(config, name))
    _require_finite_positive("detection.hw_n_std", config.hw_n_std)
    if config.hw_seasonal_period < 2:
        raise ConfigError(
            f"detection.hw_seasonal_period must be >= 2, got {config.hw_seasonal_period!r}"
        )

    _require_finite_positive("detection.markov_smoothing", config.markov_smoothing)

    if config.graph_algo_interval < 10 or config.graph_algo_interval > 100_000:
        raise ConfigError(
            f"detection.graph_algo_interval must be between 10 and 100_000, "
            f"got {config.graph_algo_interval!r}"
        )

    if config.risk_half_life_hours < 1:
        raise ConfigError(
            f"detection.risk_half_life_hours must be >= 1, got {config.risk_half_life_hours!r}"
        )
    if config.risk_threshold <= 0:
        raise ConfigError(f"detection.risk_threshold must be > 0, got {config.risk_threshold!r}")
    if config.risk_max_entities < 1:
        raise ConfigError(
            f"detection.risk_max_entities must be >= 1, got {config.risk_max_entities!r}"
        )
    if config.score_interval < 1:
        raise ConfigError(f"detection.score_interval must be >= 1, got {config.score_interval!r}")

    if config.max_template_hw < 1 or config.max_template_hw > 100_000:
        raise ConfigError(
            f"detection.max_template_hw must be between 1 and 100_000, "
            f"got {config.max_template_hw!r}"
        )
    if config.max_entity_hw < 1 or config.max_entity_hw > 100_000:
        raise ConfigError(
            f"detection.max_entity_hw must be between 1 and 100_000, got {config.max_entity_hw!r}"
        )
    if config.min_events_for_scoring < 1 or config.min_events_for_scoring > 100_000:
        raise ConfigError(
            f"detection.min_events_for_scoring must be between 1 and 100_000, "
            f"got {config.min_events_for_scoring!r}"
        )

    # Graph-structural config
    gs = config.graph_structural
    if not (0.0 < gs.betweenness_threshold <= 1.0):
        raise ConfigError(
            f"detection.graph_structural.betweenness_threshold must be in (0, 1], "
            f"got {gs.betweenness_threshold!r}"
        )
    if gs.fan_out_sigma <= 0.0:
        raise ConfigError(
            f"detection.graph_structural.fan_out_sigma must be > 0, got {gs.fan_out_sigma!r}"
        )
    if gs.fan_out_min_floor < 1:
        raise ConfigError(
            f"detection.graph_structural.fan_out_min_floor must be >= 1, "
            f"got {gs.fan_out_min_floor!r}"
        )
    if gs.fan_out_history_size < 3:
        raise ConfigError(
            f"detection.graph_structural.fan_out_history_size must be >= 3, "
            f"got {gs.fan_out_history_size!r}"
        )

    # Kill-chain config
    kc = config.kill_chain
    if kc.tactic_threshold < 2:
        raise ConfigError(
            f"detection.kill_chain.tactic_threshold must be >= 2, got {kc.tactic_threshold!r}"
        )
    if kc.window_seconds < 60:
        raise ConfigError(
            f"detection.kill_chain.window_seconds must be >= 60, got {kc.window_seconds!r}"
        )
    if kc.max_entities < 1:
        raise ConfigError(
            f"detection.kill_chain.max_entities must be >= 1, got {kc.max_entities!r}"
        )


# ---------------------------------------------------------------------------
# Threat-intelligence (TAXII) validation — S-067
# ---------------------------------------------------------------------------


_THREAT_INTEL_MIN_POLL_INTERVAL_S = 60
_THREAT_INTEL_DNS_TIMEOUT_S = 2.0


def _validate_threat_intel(config: ThreatIntelConfig) -> None:
    """Validate the threat-intel block. No-op when ``enabled`` is False."""
    if not config.enabled:
        return
    _validate_threat_intel_defaults(config)
    _validate_threat_intel_feeds_structural(config)
    _validate_threat_intel_feeds_dns(config)


def _validate_threat_intel_defaults(config: ThreatIntelConfig) -> None:
    """Scalar bounds on the top-level ``threat_intel:`` block."""
    if config.default_poll_interval_s < _THREAT_INTEL_MIN_POLL_INTERVAL_S:
        raise ConfigError(
            f"threat_intel.default_poll_interval_s must be >= "
            f"{_THREAT_INTEL_MIN_POLL_INTERVAL_S}, got {config.default_poll_interval_s!r}"
        )
    if config.request_timeout_s <= 0.0 or not math.isfinite(config.request_timeout_s):
        raise ConfigError(
            f"threat_intel.request_timeout_s must be finite and > 0, "
            f"got {config.request_timeout_s!r}"
        )
    if config.max_indicators_per_feed < 1:
        raise ConfigError(
            f"threat_intel.max_indicators_per_feed must be >= 1, "
            f"got {config.max_indicators_per_feed!r}"
        )
    if config.expired_grace_days < 0:
        raise ConfigError(
            f"threat_intel.expired_grace_days must be >= 0, got {config.expired_grace_days!r}"
        )
    if config.startup_jitter_s < 0:
        raise ConfigError(
            f"threat_intel.startup_jitter_s must be >= 0, got {config.startup_jitter_s!r}"
        )


def _validate_threat_intel_feeds_structural(config: ThreatIntelConfig) -> None:
    """Cheap per-feed checks (duplicates, scheme, scalar bounds, auth consistency).

    Runs before any DNS lookup so a misconfiguration surfaces
    deterministically without depending on network state.
    """
    from urllib.parse import urlparse

    seen_ids: set[str] = set()
    for feed in config.feeds:
        if feed.id in seen_ids:
            raise ConfigError(f"threat_intel.feeds: duplicate id {feed.id!r}")
        seen_ids.add(feed.id)
        parsed = urlparse(feed.url)
        if parsed.scheme not in ("http", "https"):
            raise ConfigError(
                f"threat_intel.feeds[{feed.id}].url scheme must be http or https, "
                f"got {parsed.scheme!r}"
            )
        if parsed.scheme == "http" and not feed.allow_insecure:
            raise ConfigError(
                f"threat_intel.feeds[{feed.id}].url must use https unless allow_insecure is true"
            )
        if not parsed.hostname:
            raise ConfigError(f"threat_intel.feeds[{feed.id}].url must include a hostname")
        if parsed.username or parsed.password:
            # URL-embedded credentials would be logged verbatim by aiohttp
            # error reprs; auth must come from `auth.api_key_env` /
            # `auth.username_env` / `auth.password_env` instead.
            raise ConfigError(
                f"threat_intel.feeds[{feed.id}].url must not contain embedded "
                "userinfo credentials; use the `auth` block with env vars"
            )
        if (
            feed.poll_interval_s is not None
            and feed.poll_interval_s < _THREAT_INTEL_MIN_POLL_INTERVAL_S
        ):
            raise ConfigError(
                f"threat_intel.feeds[{feed.id}].poll_interval_s must be >= "
                f"{_THREAT_INTEL_MIN_POLL_INTERVAL_S}, got {feed.poll_interval_s!r}"
            )
        if not (0 <= feed.confidence_floor <= 100):
            raise ConfigError(
                f"threat_intel.feeds[{feed.id}].confidence_floor must be in [0, 100], "
                f"got {feed.confidence_floor!r}"
            )
        _validate_taxii_feed_auth(feed)


def _validate_taxii_feed_auth(feed: TAXIIFeedConfig) -> None:
    """Auth-config consistency: required env-var fields per ``kind``."""
    auth = feed.auth
    if auth is None:
        return
    if auth.kind == "api_key" and not auth.api_key_env:
        raise ConfigError(
            f"threat_intel.feeds[{feed.id}].auth.api_key_env is required when kind='api_key'"
        )
    if auth.kind == "basic" and (not auth.username_env or not auth.password_env):
        raise ConfigError(
            f"threat_intel.feeds[{feed.id}].auth.username_env and password_env "
            "are required when kind='basic'"
        )


def _validate_threat_intel_feeds_dns(config: ThreatIntelConfig) -> None:
    """Per-feed SSRF / private-IP guard; literal IPs short-circuit DNS."""
    from urllib.parse import urlparse

    for feed in config.feeds:
        if feed.allow_private_addresses:
            continue
        parsed = urlparse(feed.url)
        if not parsed.hostname:
            continue
        if _check_literal_ip_or_resolve(feed.id, parsed.hostname):
            continue


def _check_literal_ip_or_resolve(feed_id: str, hostname: str) -> bool:
    """Returns True after running the appropriate path; raises on private IP."""
    import socket

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_private_ip(hostname):
            raise ConfigError(
                f"threat_intel.feeds[{feed_id}].url targets private/reserved "
                f"address {hostname!r}; set allow_private_addresses=true to override"
            )
        return True
    # DNS path with a bounded timeout so a misbehaving resolver cannot stall
    # startup. ``socket.gethostbyname`` has no timeout arg, so we use the
    # process-global default for the call and restore it immediately. This is
    # safe at single-threaded startup; do not call from worker threads.
    prev_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(_THREAT_INTEL_DNS_TIMEOUT_S)
    try:
        resolved = socket.gethostbyname(hostname)
    except OSError as exc:
        raise ConfigError(
            f"threat_intel.feeds[{feed_id}].url DNS lookup failed for {hostname!r}: {exc}"
        ) from exc
    finally:
        socket.setdefaulttimeout(prev_timeout)
    if _is_private_ip(resolved):
        raise ConfigError(
            f"threat_intel.feeds[{feed_id}].url resolves to private/reserved "
            f"address {resolved!r}; set allow_private_addresses=true to override"
        )
    return True


def validate_seerflow_config(config: SeerflowConfig) -> None:
    """Run cross-section validators on a fully built ``SeerflowConfig``."""
    _validate_threat_intel(config.threat_intel)
