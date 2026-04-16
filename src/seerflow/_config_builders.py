"""Section builders, env-var interpolation, and parsers for seerflow config.

Imports validation primitives from `seerflow._config_validation` (leaf) and
section dataclasses from `seerflow.config` (parent). The runtime cycle with
`config.py` is safe because `config.py` imports this module *after* its
dataclass block is fully defined.

Extracted from `seerflow.config` in S-172 to keep config.py under CLAUDE.md's
800-line file ceiling.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import urlparse

import yaml

from seerflow._config_validation import (
    _VALID_STORAGE_BACKENDS,
    ConfigError,
    _is_pos_int,
    _is_pos_number,
    _is_private_ip,
    _require_valid_port,
    _validate_dashboard_url,
    _validate_detection_config,
    _validate_rate_limit_string,
)
from seerflow.config import (
    AlertingConfig,
    CorrelationConfig,
    DetectionConfig,
    GraphStructuralConfig,
    KillChainConfig,
    LLMConfig,
    ReceiverConfig,
    StorageConfig,
    WebhookEndpointConfig,
)

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import WebhookTarget


# ---------------------------------------------------------------------------
# Data-dir defaults
# ---------------------------------------------------------------------------


def _default_data_dir() -> str:
    """Compute XDG-compliant default data directory (lazy, respects $XDG_DATA_HOME)."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(xdg_data_home) / "seerflow")


# ---------------------------------------------------------------------------
# Env var interpolation
# ---------------------------------------------------------------------------


_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env_var(match: re.Match[str]) -> str:
    """Resolve a single ``${VAR}`` or ``${VAR:-default}`` match."""
    expr = match.group(1)
    if ":-" in expr:
        var_name, default = expr.split(":-", 1)
        return os.environ.get(var_name, default)
    var_name = expr
    value = os.environ.get(var_name)
    if value is None:
        msg = f"Required environment variable ${{{var_name}}} is not set"
        raise ConfigError(msg)
    return value


def _interpolate_env_vars(value: str) -> str:
    """Replace all ``${VAR}`` and ``${VAR:-default}`` in a string."""
    return _ENV_VAR_PATTERN.sub(_resolve_env_var, value)


def _walk_and_interpolate(obj: Any) -> Any:
    """Recursively walk a dict/list and interpolate env vars in strings."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_interpolate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_interpolate(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Section constructors
# ---------------------------------------------------------------------------


def _build_storage(data: dict[str, Any]) -> StorageConfig:
    data_dir = data.get("data_dir") or None
    if data_dir is None:
        data_dir = os.environ.get("SEERFLOW_DATA_DIR") or _default_data_dir()
    sqlite_path = data.get("sqlite_path") or str(Path(data_dir) / "seerflow.db")
    backend = data.get("backend", "sqlite")
    if backend not in _VALID_STORAGE_BACKENDS:
        valid = sorted(_VALID_STORAGE_BACKENDS)
        msg = f"Invalid storage.backend {backend!r}. Must be one of {valid}"
        raise ConfigError(msg)
    return StorageConfig(
        backend=backend,
        data_dir=data_dir,
        sqlite_path=sqlite_path,
        postgresql_url=data.get("postgresql_url", ""),
    )


def _build_webhook_configs(raw: Any) -> tuple[WebhookEndpointConfig, ...]:
    """Parse raw webhook config entries into a tuple of WebhookEndpointConfig."""
    if not isinstance(raw, list):
        return ()
    configs: list[WebhookEndpointConfig] = []
    for wh in raw:
        if not isinstance(wh, dict):
            msg = "Each webhook entry must be a mapping"
            raise ConfigError(msg)
        fm = wh.get("field_mapping", {})
        if isinstance(fm, dict):
            fm = {str(k): str(v) for k, v in fm.items()}
        configs.append(
            WebhookEndpointConfig(
                path=wh.get("path", "/ingest/webhook"),
                auth_header=wh.get("auth_header", ""),
                auth_token=wh.get("auth_token", ""),
                field_mapping=fm,
                source_id=wh.get("source_id", "webhook"),
            )
        )
    return tuple(configs)


def _build_receivers(data: dict[str, Any]) -> ReceiverConfig:
    file_paths = data.get("file_paths", ())
    if isinstance(file_paths, list):
        file_paths = tuple(str(p) for p in file_paths)
    allowed_log_roots = data.get("allowed_log_roots", ())
    if isinstance(allowed_log_roots, list):
        allowed_log_roots = tuple(str(r) for r in allowed_log_roots)
    cfg = ReceiverConfig(
        syslog_enabled=data.get("syslog_enabled", True),
        syslog_udp_port=data.get("syslog_udp_port", 514),
        syslog_tcp_port=data.get("syslog_tcp_port", 601),
        syslog_tcp_enabled=data.get("syslog_tcp_enabled", True),
        otlp_grpc_enabled=data.get("otlp_grpc_enabled", True),
        otlp_grpc_port=data.get("otlp_grpc_port", 4317),
        otlp_grpc_max_workers=data.get("otlp_grpc_max_workers", 4),
        otlp_http_enabled=data.get("otlp_http_enabled", True),
        otlp_http_port=data.get("otlp_http_port", 4318),
        otlp_http_max_request_bytes=data.get("otlp_http_max_request_bytes", 4_194_304),
        file_paths=file_paths,
        file_checkpoint_dir=data.get("file_checkpoint_dir", ""),
        file_debounce_ms=data.get("file_debounce_ms", 1600),
        allowed_log_roots=allowed_log_roots,
        webhooks=_build_webhook_configs(data.get("webhooks", ())),
        webhook_enabled=data.get("webhook_enabled", False),
        webhook_port=data.get("webhook_port", 8081),
        bind_addr=data.get("bind_addr", "0.0.0.0"),  # noqa: S104  # nosec B104
        queue_maxsize=data.get("queue_maxsize", 10_000),
    )
    _require_valid_port("receivers.syslog_udp_port", cfg.syslog_udp_port)
    _require_valid_port("receivers.syslog_tcp_port", cfg.syslog_tcp_port)
    _require_valid_port("receivers.otlp_grpc_port", cfg.otlp_grpc_port)
    _require_valid_port("receivers.otlp_http_port", cfg.otlp_http_port)
    _require_valid_port("receivers.webhook_port", cfg.webhook_port)
    if cfg.queue_maxsize < 1 or cfg.queue_maxsize > 1_000_000:
        raise ConfigError(
            f"receivers.queue_maxsize must be between 1 and 1000000, got {cfg.queue_maxsize!r}"
        )
    if cfg.otlp_http_max_request_bytes < 1 or cfg.otlp_http_max_request_bytes > 100_000_000:
        raise ConfigError(
            f"receivers.otlp_http_max_request_bytes must be between 1 and 100000000, "
            f"got {cfg.otlp_http_max_request_bytes!r}"
        )
    return cfg


def _build_graph_structural(data: dict[str, Any]) -> GraphStructuralConfig:
    """Build GraphStructuralConfig from a YAML ``graph_structural:`` section."""
    return GraphStructuralConfig(
        community_crossing_enabled=data.get("community_crossing_enabled", True),
        betweenness_threshold=data.get("betweenness_threshold", 0.3),
        fan_out_sigma=data.get("fan_out_sigma", 3.0),
        fan_out_min_floor=data.get("fan_out_min_floor", 5),
        fan_out_history_size=data.get("fan_out_history_size", 20),
    )


def _build_kill_chain(data: dict[str, Any]) -> KillChainConfig:
    """Build KillChainConfig from a YAML ``kill_chain:`` section."""
    return KillChainConfig(
        enabled=data.get("enabled", True),
        tactic_threshold=data.get("tactic_threshold", 3),
        window_seconds=data.get("window_seconds", 86400),
        max_entities=data.get("max_entities", 10_000),
    )


def _build_detection(data: dict[str, Any]) -> DetectionConfig:
    """Build DetectionConfig from a YAML ``detection:`` section.

    Precedence for detector sub-params (HW, CUSUM, Markov):
    nested key wins over flat key, flat key wins over hardcoded default.
    Example: ``hw.alpha`` > ``hw_alpha`` > ``0.3``.
    """
    dspot = data.get("dspot", {})
    hw = data.get("hw", {})
    cusum = data.get("cusum", {})
    markov = data.get("markov", {})
    raw_sigma_dirs = data.get("sigma_rules_dirs", ())
    if isinstance(raw_sigma_dirs, list):
        sigma_rules_dirs = tuple(str(d) for d in raw_sigma_dirs)
    elif raw_sigma_dirs == ():
        sigma_rules_dirs = ()
    else:
        raise ConfigError(
            f"detection.sigma_rules_dirs must be a list, got {type(raw_sigma_dirs).__name__!r}"
        )
    config = DetectionConfig(
        hst_window_size=data.get("hst_window_size", 1000),
        hst_n_trees=data.get("hst_n_trees", 25),
        dspot_calibration_window=dspot.get("calibration_window", 1000),
        dspot_risk_level=dspot.get("risk_level", 0.0001),
        dspot_initial_percentile=dspot.get("initial_percentile", 98),
        dspot_threshold_cap_multiplier=dspot.get("threshold_cap_multiplier", 5.0),
        hw_seasonal_period=hw.get("seasonal_period", data.get("hw_seasonal_period", 1440)),
        hw_alpha=hw.get("alpha", data.get("hw_alpha", 0.3)),
        hw_beta=hw.get("beta", data.get("hw_beta", 0.1)),
        hw_gamma=hw.get("gamma", data.get("hw_gamma", 0.1)),
        hw_n_std=hw.get("n_std", data.get("hw_n_std", 3.0)),
        cusum_drift=cusum.get("drift", data.get("cusum_drift", 0.5)),
        cusum_threshold=cusum.get("threshold", data.get("cusum_threshold", 5.0)),
        cusum_ema_alpha=cusum.get("ema_alpha", data.get("cusum_ema_alpha", 0.1)),
        cusum_warmup_buckets=cusum.get("warmup_buckets", data.get("cusum_warmup_buckets", 30)),
        markov_smoothing=markov.get("smoothing", data.get("markov_smoothing", 1e-6)),
        markov_min_events=markov.get("min_events", data.get("markov_min_events", 100)),
        markov_max_entities=markov.get("max_entities", data.get("markov_max_entities", 1000)),
        max_sources=data.get("max_sources", 256),
        model_save_interval_seconds=data.get("model_save_interval_seconds", 300),
        weights_content=data.get("weights_content", 0.30),
        weights_volume=data.get("weights_volume", 0.25),
        weights_sequence=data.get("weights_sequence", 0.25),
        weights_pattern=data.get("weights_pattern", 0.20),
        graph_algo_interval=data.get("graph_algo_interval", 500),
        risk_half_life_hours=data.get("risk_half_life_hours", 4),
        risk_threshold=float(data.get("risk_threshold", 50.0)),
        risk_max_entities=data.get("risk_max_entities", 10_000),
        score_interval=data.get("score_interval", 1),
        max_template_hw=data.get("max_template_hw", 500),
        max_entity_hw=data.get("max_entity_hw", 500),
        min_events_for_scoring=data.get("min_events_for_scoring", 50),
        weights_template_volume=data.get("weights_template_volume", 0.15),
        weights_entity_volume=data.get("weights_entity_volume", 0.15),
        sigma_rules_dirs=sigma_rules_dirs,
        attack_mappings=tuple(data.get("attack_mappings", ())),
        graph_structural=_build_graph_structural(data.get("graph_structural", {})),
        kill_chain=_build_kill_chain(data.get("kill_chain", {})),
    )
    _validate_detection_config(config)
    return config


def _build_correlation(data: dict[str, Any]) -> CorrelationConfig:
    """Build CorrelationConfig from a YAML ``correlation:`` section."""
    rule_dirs_raw = data.get("rule_dirs", ())
    rule_dirs = tuple(str(d) for d in rule_dirs_raw) if isinstance(rule_dirs_raw, list) else ()
    config = CorrelationConfig(
        window_duration_seconds=data.get("window_duration_seconds", 1800),
        max_events_per_entity=data.get("max_events_per_entity", 1000),
        max_entities=data.get("max_entities", 10_000),
        late_tolerance_seconds=data.get("late_tolerance_seconds", 30),
        rule_dirs=rule_dirs,
    )
    if config.late_tolerance_seconds < 0:
        raise ConfigError(
            f"correlation.late_tolerance_seconds must be >= 0, "
            f"got {config.late_tolerance_seconds!r}"
        )
    if config.window_duration_seconds < 1:
        raise ConfigError(
            f"correlation.window_duration_seconds must be >= 1, "
            f"got {config.window_duration_seconds!r}"
        )
    if config.max_events_per_entity < 1:
        raise ConfigError(
            f"correlation.max_events_per_entity must be >= 1, got {config.max_events_per_entity!r}"
        )
    if config.max_entities < 1:
        raise ConfigError(f"correlation.max_entities must be >= 1, got {config.max_entities!r}")
    return config


_VALID_WEBHOOK_FORMATS = frozenset({"slack", "teams", "json"})


def _build_webhook_targets(raw_webhooks: tuple[dict[str, Any], ...]) -> tuple[WebhookTarget, ...]:
    """Parse raw webhook dicts into a tuple of WebhookTarget objects."""
    from seerflow.alerting.dispatcher import WebhookTarget

    targets: list[WebhookTarget] = []
    for wh in raw_webhooks:
        url = wh.get("url", "")
        if not url:
            raise ConfigError("alerting.webhooks[*].url must be a non-empty string")
        from urllib.parse import urlparse as _urlparse

        _parsed = _urlparse(url)
        if _parsed.scheme not in ("http", "https"):
            raise ConfigError(
                f"alerting.webhooks[*].url must use http or https, got {_parsed.scheme!r}"
            )
        if _is_private_ip(_parsed.hostname):
            raise ConfigError(
                f"alerting.webhooks[*].url must not target private/reserved IP: {_parsed.hostname}"
            )
        fmt = wh.get("format", "")
        if fmt not in _VALID_WEBHOOK_FORMATS:
            valid = sorted(_VALID_WEBHOOK_FORMATS)
            raise ConfigError(f"alerting.webhooks[*].format must be one of {valid}, got {fmt!r}")
        min_severity = wh.get("min_severity", 0)
        if not isinstance(min_severity, int) or isinstance(min_severity, bool) or min_severity < 0:
            raise ConfigError(
                f"alerting.webhooks[*].min_severity must be an integer >= 0, got {min_severity!r}"
            )
        targets.append(WebhookTarget(url=url, format=fmt, min_severity=min_severity))
    return tuple(targets)


def _parse_dedup_overrides(raw: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    parsed: list[tuple[str, int]] = []
    for k, v in raw.items():
        try:
            seconds = int(v)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"alerting.dedup_window_overrides[{k!r}] must be an integer, got {v!r}"
            ) from exc
        if seconds < 1:
            raise ConfigError(
                f"alerting.dedup_window_overrides[{k!r}] must be >= 1, got {seconds}"
            )
        parsed.append((str(k), seconds))
    return tuple(parsed)


def _build_alerting(data: dict[str, Any]) -> AlertingConfig:
    webhooks = data.get("webhooks", ())
    if isinstance(webhooks, list):
        webhooks = tuple(webhooks)
    raw_overrides = data.get("dedup_window_overrides", {})
    overrides: tuple[tuple[str, int], ...] = ()
    if isinstance(raw_overrides, dict):
        overrides = _parse_dedup_overrides(raw_overrides)
    dedup_window_seconds = data.get("dedup_window_seconds", 900)
    if (
        not isinstance(dedup_window_seconds, int)
        or isinstance(dedup_window_seconds, bool)
        or dedup_window_seconds < 1
    ):
        raise ConfigError(
            f"alerting.dedup_window_seconds must be an integer >= 1, got {dedup_window_seconds!r}"
        )
    webhook_targets = _build_webhook_targets(webhooks)
    dashboard_url = data.get("dashboard_url", "")
    if not isinstance(dashboard_url, str):
        raise ConfigError(
            f"alerting.dashboard_url must be a string, got {type(dashboard_url).__name__}"
        )
    if dashboard_url:
        _validate_dashboard_url(dashboard_url)
    routing_key = data.get("pagerduty_routing_key", "")
    if routing_key and not re.fullmatch(r"[0-9a-fA-F]{32}", routing_key):
        raise ConfigError("alerting.pagerduty_routing_key must be a 32-character hex string")
    otlp_endpoint = data.get("otlp_endpoint", "")
    if not isinstance(otlp_endpoint, str):
        raise ConfigError(
            f"alerting.otlp_endpoint must be a string, got {type(otlp_endpoint).__name__}"
        )
    if otlp_endpoint and "://" in otlp_endpoint:
        _allowed_otlp_schemes = {"http", "https"}
        parsed_ep = urlparse(otlp_endpoint)
        if parsed_ep.scheme not in _allowed_otlp_schemes:
            raise ConfigError(
                f"alerting.otlp_endpoint: unsupported scheme {parsed_ep.scheme!r},"
                " expected http, https, or bare host:port"
            )
    otlp_protocol = data.get("otlp_protocol", "grpc")
    if otlp_protocol not in ("grpc", "http"):
        raise ConfigError(
            f"alerting.otlp_protocol must be 'grpc' or 'http', got {otlp_protocol!r}"
        )
    otlp_interval = data.get("otlp_export_interval_seconds", 5)
    if not isinstance(otlp_interval, int) or isinstance(otlp_interval, bool) or otlp_interval < 1:
        raise ConfigError(
            f"alerting.otlp_export_interval_seconds must be an integer >= 1, got {otlp_interval!r}"
        )
    return AlertingConfig(
        dedup_window_seconds=dedup_window_seconds,
        dedup_window_overrides=overrides,
        webhooks=webhooks,
        webhook_targets=webhook_targets,
        pagerduty_routing_key=routing_key,
        dashboard_url=dashboard_url,
        otlp_endpoint=otlp_endpoint,
        otlp_protocol=otlp_protocol,
        otlp_export_interval_seconds=otlp_interval,
    )


def _build_llm(data: dict[str, Any]) -> LLMConfig:
    return LLMConfig(
        backend=data.get("backend", ""),
        model_path=data.get("model_path", ""),
        ollama_url=data.get("ollama_url", "http://localhost:11434"),
    )


def _load_yaml_file(config_path: Path) -> dict[str, Any]:
    """Load and validate a YAML config file, returning the parsed mapping."""
    try:
        with config_path.open() as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse config file {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must be a YAML mapping, got {type(raw).__name__}")
    return raw


# ---------------------------------------------------------------------------
# WebSocket field parser (ws_*)
# ---------------------------------------------------------------------------


_WS_QUEUE_MAXLEN_CEILING = 100_000
_WS_MAX_CONNECTIONS_CEILING = 1_000
_WS_BATCH_MAX_EVENTS_CEILING = 1_000


class _WsFields(NamedTuple):
    """Parsed ``ws_*`` WebSocket tuning fields from a raw config dict."""

    ws_max_connections: int
    ws_queue_maxlen: int
    ws_tick_interval_s: float
    ws_batch_max_events: int
    ws_status_interval_s: float
    ws_allowed_origins: tuple[str, ...]
    ws_filter_min_interval_ms: int


def _parse_ws_fields(
    raw: dict[str, Any],
) -> _WsFields:
    """Parse and validate the top-level ``ws_*`` WebSocket tuning fields."""
    ws_max_connections = raw.get("ws_max_connections", 20)
    if not _is_pos_int(ws_max_connections) or ws_max_connections > _WS_MAX_CONNECTIONS_CEILING:
        raise ConfigError(
            f"ws_max_connections must be an integer in [1, {_WS_MAX_CONNECTIONS_CEILING}], "
            f"got {ws_max_connections!r}"
        )

    ws_queue_maxlen = raw.get("ws_queue_maxlen", 1000)
    if not _is_pos_int(ws_queue_maxlen) or ws_queue_maxlen > _WS_QUEUE_MAXLEN_CEILING:
        raise ConfigError(
            f"ws_queue_maxlen must be an integer in [1, {_WS_QUEUE_MAXLEN_CEILING}], "
            f"got {ws_queue_maxlen!r}"
        )

    ws_tick_interval_s = raw.get("ws_tick_interval_s", 0.01)
    if not _is_pos_number(ws_tick_interval_s):
        raise ConfigError(
            f"ws_tick_interval_s must be a positive number, got {ws_tick_interval_s!r}"
        )

    ws_batch_max_events = raw.get("ws_batch_max_events", 10)
    if not _is_pos_int(ws_batch_max_events) or ws_batch_max_events > _WS_BATCH_MAX_EVENTS_CEILING:
        raise ConfigError(
            f"ws_batch_max_events must be an integer in [1, {_WS_BATCH_MAX_EVENTS_CEILING}], "
            f"got {ws_batch_max_events!r}"
        )

    ws_status_interval_s = raw.get("ws_status_interval_s", 5.0)
    if not _is_pos_number(ws_status_interval_s):
        raise ConfigError(
            f"ws_status_interval_s must be a positive number, got {ws_status_interval_s!r}"
        )

    ws_allowed_origins_raw = raw.get("ws_allowed_origins", [])
    if not isinstance(ws_allowed_origins_raw, list):
        raise ConfigError(
            f"ws_allowed_origins must be a list of strings, got "
            f"{type(ws_allowed_origins_raw).__name__}"
        )
    if not all(isinstance(o, str) for o in ws_allowed_origins_raw):
        raise ConfigError("ws_allowed_origins items must be strings")
    ws_allowed_origins: tuple[str, ...] = tuple(ws_allowed_origins_raw)

    ws_filter_min_interval_ms = raw.get("ws_filter_min_interval_ms", 100)
    if (
        not isinstance(ws_filter_min_interval_ms, int)
        or isinstance(ws_filter_min_interval_ms, bool)
        or ws_filter_min_interval_ms < 0
    ):
        raise ConfigError(
            f"ws_filter_min_interval_ms must be a non-negative integer, "
            f"got {ws_filter_min_interval_ms!r}"
        )

    return _WsFields(
        ws_max_connections=ws_max_connections,
        ws_queue_maxlen=ws_queue_maxlen,
        ws_tick_interval_s=float(ws_tick_interval_s),
        ws_batch_max_events=ws_batch_max_events,
        ws_status_interval_s=float(ws_status_interval_s),
        ws_allowed_origins=ws_allowed_origins,
        ws_filter_min_interval_ms=ws_filter_min_interval_ms,
    )


# ---------------------------------------------------------------------------
# API hardening field parser (api_*)
# ---------------------------------------------------------------------------


class _ApiFields(NamedTuple):
    """Parsed ``api_*`` fields from a raw config dict (S-181)."""

    api_rate_limit_enabled: bool
    api_rate_limit_redis_url: str | None
    api_allowed_origins: tuple[str, ...]
    api_list_rate_limit: str
    api_detail_rate_limit: str
    api_coverage_rate_limit: str
    api_trust_proxy_headers: bool


def _parse_api_fields(raw: dict[str, Any]) -> _ApiFields:
    """Parse and validate the top-level ``api_*`` API-hardening fields."""
    enabled_raw = raw.get("api_rate_limit_enabled", True)
    if not isinstance(enabled_raw, bool):
        raise ConfigError(
            f"api_rate_limit_enabled must be a boolean, got {type(enabled_raw).__name__}"
        )

    redis_url_raw = raw.get("api_rate_limit_redis_url")
    if redis_url_raw is not None:
        if not isinstance(redis_url_raw, str) or not redis_url_raw.strip():
            raise ConfigError("api_rate_limit_redis_url must be a non-empty string or omitted")
        redis_url: str | None = redis_url_raw.strip()
    else:
        redis_url = None

    origins_raw = raw.get("api_allowed_origins", [])
    if origins_raw is None:
        origins_raw = []
    if not isinstance(origins_raw, list):
        raise ConfigError(
            f"api_allowed_origins must be a list of strings, got {type(origins_raw).__name__}"
        )
    if not all(isinstance(o, str) for o in origins_raw):
        raise ConfigError("api_allowed_origins items must be strings")
    for origin in origins_raw:
        if origin == "*":
            raise ConfigError(
                "api_allowed_origins must not contain '*' — wildcard defeats "
                "the purpose of the allowlist. Enumerate explicit origins."
            )
        if not (origin.startswith("http://") or origin.startswith("https://")):
            raise ConfigError(
                f"api_allowed_origins entries must start with http:// or https://, got {origin!r}"
            )
    origins: tuple[str, ...] = tuple(origins_raw)

    list_limit_str = _validate_rate_limit_string(
        "api_list_rate_limit", str(raw.get("api_list_rate_limit", "60/minute"))
    )
    detail_limit_str = _validate_rate_limit_string(
        "api_detail_rate_limit", str(raw.get("api_detail_rate_limit", "300/minute"))
    )
    coverage_limit_str = _validate_rate_limit_string(
        "api_coverage_rate_limit", str(raw.get("api_coverage_rate_limit", "10/minute"))
    )

    trust_proxy_raw = raw.get("api_trust_proxy_headers", False)
    if not isinstance(trust_proxy_raw, bool):
        raise ConfigError(
            f"api_trust_proxy_headers must be a boolean, got {type(trust_proxy_raw).__name__}"
        )

    return _ApiFields(
        api_rate_limit_enabled=enabled_raw,
        api_rate_limit_redis_url=redis_url,
        api_allowed_origins=origins,
        api_list_rate_limit=list_limit_str,
        api_detail_rate_limit=detail_limit_str,
        api_coverage_rate_limit=coverage_limit_str,
        api_trust_proxy_headers=trust_proxy_raw,
    )
