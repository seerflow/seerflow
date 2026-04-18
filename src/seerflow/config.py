"""YAML config loader with ``${ENV_VAR:-default}`` interpolation.

Config is loaded once at startup. Every component reads from the resulting
``SeerflowConfig`` instance. If no config file is found, sensible defaults
are used (zero-config first run per NFR-006).
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import WebhookTarget
    from seerflow.alerting.router import DefaultRouting, QuietHours, RoutingRule

# Re-exports from seerflow._config_validation — preserves `from seerflow.config
# import ConfigError` for public callers (S-172 split). Explicit `X as X` form
# marks these as intentional re-exports for mypy strict mode.
from seerflow._config_validation import _VALID_LOG_LEVELS as _VALID_LOG_LEVELS
from seerflow._config_validation import (
    _VALID_STORAGE_BACKENDS as _VALID_STORAGE_BACKENDS,
)
from seerflow._config_validation import ConfigError as ConfigError
from seerflow._config_validation import _require_valid_port as _require_valid_port

# ---------------------------------------------------------------------------
# Section dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class StorageConfig:
    """Storage backend configuration."""

    backend: str = "sqlite"
    data_dir: str = ""
    sqlite_path: str = ""
    postgresql_url: str = field(default="", repr=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class WebhookEndpointConfig:
    """Configuration for a single webhook endpoint (YAML-loadable)."""

    path: str = "/ingest/webhook"
    auth_header: str = ""
    auth_token: str = field(default="", repr=False)
    field_mapping: dict[str, str] = field(default_factory=dict)
    source_id: str = "webhook"

    def __post_init__(self) -> None:
        if bool(self.auth_header) != bool(self.auth_token):
            msg = "auth_header and auth_token must both be set or both be empty"
            raise ConfigError(msg)


@dataclass(frozen=True, kw_only=True, slots=True)
class ReceiverConfig:
    """Log receiver configuration."""

    syslog_enabled: bool = True
    syslog_udp_port: int = 514
    syslog_tcp_port: int = 601
    syslog_tcp_enabled: bool = True
    otlp_grpc_enabled: bool = True
    otlp_grpc_port: int = 4317
    otlp_grpc_max_workers: int = 4
    otlp_http_enabled: bool = True
    otlp_http_port: int = 4318
    otlp_http_max_request_bytes: int = 4_194_304
    file_paths: tuple[str, ...] = ()
    file_checkpoint_dir: str = ""
    file_debounce_ms: int = 1600
    allowed_log_roots: tuple[str, ...] = ()
    webhooks: tuple[WebhookEndpointConfig, ...] = ()
    webhook_enabled: bool = False
    webhook_port: int = 8081
    bind_addr: str = "0.0.0.0"  # noqa: S104  # nosec B104
    queue_maxsize: int = 10_000


@dataclass(frozen=True, kw_only=True, slots=True)
class GraphStructuralConfig:
    """Graph-structural correlation thresholds."""

    community_crossing_enabled: bool = True
    betweenness_threshold: float = 0.3
    fan_out_sigma: float = 3.0
    fan_out_min_floor: int = 5
    fan_out_history_size: int = 20


@dataclass(frozen=True, kw_only=True, slots=True)
class KillChainConfig:
    """Kill-chain tactic progression detection."""

    enabled: bool = True
    tactic_threshold: int = 3
    window_seconds: int = 86400  # 24h
    max_entities: int = 10_000


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectionConfig:
    """ML detection configuration."""

    hst_window_size: int = 1000
    hst_n_trees: int = 25
    dspot_calibration_window: int = 1000
    dspot_risk_level: float = 0.0001
    dspot_initial_percentile: int = 98
    dspot_threshold_cap_multiplier: float = 5.0
    hw_seasonal_period: int = 1440
    hw_alpha: float = 0.3
    hw_beta: float = 0.1
    hw_gamma: float = 0.1
    hw_n_std: float = 3.0
    cusum_drift: float = 0.5
    cusum_threshold: float = 5.0
    cusum_ema_alpha: float = 0.1
    cusum_warmup_buckets: int = 30
    markov_smoothing: float = 1e-6
    markov_min_events: int = 100
    markov_max_entities: int = 1000
    max_sources: int = 256
    model_save_interval_seconds: int = 300
    # Weights do NOT need to sum to 1.0 — the blending pipeline divides by
    # the sum of all weights, so only ratios matter.
    weights_content: float = 0.30
    weights_volume: float = 0.25
    weights_sequence: float = 0.25
    weights_pattern: float = 0.20
    graph_algo_interval: int = 500
    risk_half_life_hours: int = 4
    risk_threshold: float = 50.0
    risk_max_entities: int = 10_000
    score_interval: int = 1  # Score every Nth event per source (1 = every event)
    max_template_hw: int = 500
    max_entity_hw: int = 500
    min_events_for_scoring: int = 50
    weights_template_volume: float = 0.15
    weights_entity_volume: float = 0.15
    sigma_rules_dirs: tuple[str, ...] = ()  # wired into pipeline startup when Sigma is integrated
    attack_mappings: tuple[dict[str, Any], ...] = ()
    graph_structural: GraphStructuralConfig = field(default_factory=GraphStructuralConfig)
    kill_chain: KillChainConfig = field(default_factory=KillChainConfig)


def _default_routing_drop() -> DefaultRouting:
    """Default-factory for AlertingConfig.default_routing (avoids import cycle)."""
    from seerflow.alerting.router import DefaultRouting

    return DefaultRouting(action="drop")


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertingConfig:
    """Alert routing configuration."""

    dedup_window_seconds: int = 900
    dedup_window_overrides: tuple[tuple[str, int], ...] = ()
    webhooks: tuple[dict[str, Any], ...] = ()
    webhook_targets: tuple[WebhookTarget, ...] = ()
    routing_rules: tuple[RoutingRule, ...] = ()
    default_routing: DefaultRouting = field(default_factory=_default_routing_drop)
    quiet_hours_by_channel: tuple[tuple[str, QuietHours], ...] = ()
    pagerduty_routing_key: str = field(default="", repr=False)
    dashboard_url: str = ""
    otlp_endpoint: str = ""
    otlp_protocol: Literal["grpc", "http"] = "grpc"
    otlp_export_interval_seconds: int = 5


@dataclass(frozen=True, kw_only=True, slots=True)
class CorrelationConfig:
    """Correlation engine configuration."""

    window_duration_seconds: int = 1800  # 30 minutes
    max_events_per_entity: int = 1000
    max_entities: int = 10_000
    late_tolerance_seconds: int = 30
    rule_dirs: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class LLMConfig:
    """LLM backend configuration."""

    backend: str = ""
    model_path: str = ""
    ollama_url: str = "http://localhost:11434"


@dataclass(frozen=True, kw_only=True, slots=True)
class SeerflowConfig:
    """Top-level Seerflow configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    receivers: ReceiverConfig = field(default_factory=ReceiverConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    dashboard_port: int = 8080
    health_bind_address: str = "127.0.0.1"
    log_level: str = "INFO"
    ws_max_connections: int = 20
    ws_queue_maxlen: int = 1000
    ws_tick_interval_s: float = 0.01
    ws_batch_max_events: int = 10
    ws_status_interval_s: float = 5.0
    # Explicit WebSocket Origin allowlist. Empty tuple means "use the
    # localhost defaults derived from dashboard_port" (see api.app).
    ws_allowed_origins: tuple[str, ...] = ()
    ws_filter_min_interval_ms: int = 100
    # API hardening (S-181).
    api_rate_limit_enabled: bool = True
    # repr=False: Redis URLs may embed credentials; redact_config masks
    # this in GET /api/v1/config.
    api_rate_limit_redis_url: str | None = field(default=None, repr=False)
    api_allowed_origins: tuple[str, ...] = ()
    api_list_rate_limit: str = "60/minute"
    api_detail_rate_limit: str = "300/minute"
    api_coverage_rate_limit: str = "10/minute"
    api_trust_proxy_headers: bool = False


# Deferred imports from seerflow._config_builders. Placed AFTER dataclasses so
# the builder module can resolve section dataclass symbols when it is imported.
# Also re-exports private helpers used by tests/unit/test_config.py (S-172).
# Explicit `X as X` form marks each as an intentional re-export for mypy strict.
from seerflow._config_builders import (  # noqa: E402
    _ApiFields as _ApiFields,
)
from seerflow._config_builders import (  # noqa: E402
    _build_alerting as _build_alerting,
)
from seerflow._config_builders import (  # noqa: E402
    _build_correlation as _build_correlation,
)
from seerflow._config_builders import (  # noqa: E402
    _build_detection as _build_detection,
)
from seerflow._config_builders import (  # noqa: E402
    _build_graph_structural as _build_graph_structural,
)
from seerflow._config_builders import (  # noqa: E402
    _build_kill_chain as _build_kill_chain,
)
from seerflow._config_builders import (  # noqa: E402
    _build_llm as _build_llm,
)
from seerflow._config_builders import (  # noqa: E402
    _build_receivers as _build_receivers,
)
from seerflow._config_builders import (  # noqa: E402
    _build_storage as _build_storage,
)
from seerflow._config_builders import (  # noqa: E402
    _build_webhook_configs as _build_webhook_configs,
)
from seerflow._config_builders import (  # noqa: E402
    _build_webhook_targets as _build_webhook_targets,
)
from seerflow._config_builders import (  # noqa: E402
    _default_data_dir as _default_data_dir,
)
from seerflow._config_builders import (  # noqa: E402
    _load_yaml_file as _load_yaml_file,
)
from seerflow._config_builders import (  # noqa: E402
    _parse_api_fields as _parse_api_fields,
)
from seerflow._config_builders import (  # noqa: E402
    _parse_dedup_overrides as _parse_dedup_overrides,
)
from seerflow._config_builders import (  # noqa: E402
    _parse_ws_fields as _parse_ws_fields,
)
from seerflow._config_builders import (  # noqa: E402
    _walk_and_interpolate as _walk_and_interpolate,
)
from seerflow._config_builders import (  # noqa: E402
    _WsFields as _WsFields,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    path: str | None = None,
    *,
    search_dir: Path | None = None,
) -> SeerflowConfig:
    """Load Seerflow configuration from a YAML file.

    Args:
        path: Explicit config file path. ``None`` searches for
            ``seerflow.yaml`` in *search_dir* (default: CWD).
        search_dir: Directory to search when *path* is ``None``.

    Raises:
        ConfigError: On missing file, bad YAML, or invalid values.
    """
    raw: dict[str, Any] = {}

    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {path}")
        raw = _load_yaml_file(config_path)
    else:
        candidate = (search_dir or Path.cwd()) / "seerflow.yaml"
        if candidate.exists():
            raw = _load_yaml_file(candidate)

    # Interpolate env vars in all string values
    raw = _walk_and_interpolate(raw)

    log_level = raw.get("log_level", "INFO")
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"Invalid log_level {log_level!r}. Must be one of {sorted(_VALID_LOG_LEVELS)}"
        )

    dashboard_port = raw.get("dashboard_port", 8080)
    _require_valid_port("dashboard_port", dashboard_port)

    health_bind_address = raw.get("health_bind_address", "127.0.0.1")
    if not isinstance(health_bind_address, str):
        raise ConfigError(
            f"health_bind_address must be a string, got {type(health_bind_address).__name__}"
        )
    try:
        ipaddress.ip_address(health_bind_address)
    except ValueError as exc:
        raise ConfigError(
            f"health_bind_address is not a valid IP address: {health_bind_address!r}"
        ) from exc

    ws_fields = _parse_ws_fields(raw)
    api_fields = _parse_api_fields(raw)

    return SeerflowConfig(
        storage=_build_storage(raw.get("storage", {})),
        receivers=_build_receivers(raw.get("receivers", {})),
        detection=_build_detection(raw.get("detection", {})),
        correlation=_build_correlation(raw.get("correlation", {})),
        alerting=_build_alerting(raw.get("alerting", {})),
        llm=_build_llm(raw.get("llm", {})),
        dashboard_port=dashboard_port,
        health_bind_address=health_bind_address,
        log_level=log_level,
        ws_max_connections=ws_fields.ws_max_connections,
        ws_queue_maxlen=ws_fields.ws_queue_maxlen,
        ws_tick_interval_s=ws_fields.ws_tick_interval_s,
        ws_batch_max_events=ws_fields.ws_batch_max_events,
        ws_status_interval_s=ws_fields.ws_status_interval_s,
        ws_allowed_origins=ws_fields.ws_allowed_origins,
        ws_filter_min_interval_ms=ws_fields.ws_filter_min_interval_ms,
        api_rate_limit_enabled=api_fields.api_rate_limit_enabled,
        api_rate_limit_redis_url=api_fields.api_rate_limit_redis_url,
        api_allowed_origins=api_fields.api_allowed_origins,
        api_list_rate_limit=api_fields.api_list_rate_limit,
        api_detail_rate_limit=api_fields.api_detail_rate_limit,
        api_coverage_rate_limit=api_fields.api_coverage_rate_limit,
        api_trust_proxy_headers=api_fields.api_trust_proxy_headers,
    )
