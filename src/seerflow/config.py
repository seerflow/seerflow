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
    from seerflow.alerting.channels.email import EmailTarget
    from seerflow.alerting.channels.sms import SmsTarget
    from seerflow.alerting.channels.telegram import TelegramTarget
    from seerflow.alerting.channels.whatsapp import WhatsAppTarget
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
    """Storage backend configuration.

    The ``postgresql_*`` knobs apply only when ``backend == "postgresql"``;
    they are accepted on every config so callers do not need to branch on
    backend when reading them. Pool defaults (min=2, max=10, command
    timeout 30s) are conservative — enough for a single Seerflow process
    serving a dashboard plus the ingest pipeline.
    """

    backend: Literal["sqlite", "postgresql"] = "sqlite"
    data_dir: str = ""
    sqlite_path: str = ""
    postgresql_url: str = field(default="", repr=False)
    # S-073: asyncpg connection-pool knobs. Defaults preserve existing
    # SQLite-only behaviour and are validated by ``_validate_postgres_pool``.
    postgresql_pool_min_size: int = 2
    postgresql_pool_max_size: int = 10
    postgresql_command_timeout_s: float = 30.0


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
    # S-151: directory where the dashboard upload UI persists custom Sigma rules.
    # Always discovered at startup regardless of ``sigma_rules_dirs`` so uploaded
    # rules survive restart without operator config gymnastics.
    sigma_custom_upload_dir: str | None = None
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
    email_targets: tuple[EmailTarget, ...] = ()
    sms_targets: tuple[SmsTarget, ...] = ()
    telegram_targets: tuple[TelegramTarget, ...] = ()
    whatsapp_targets: tuple[WhatsAppTarget, ...] = ()
    routing_rules: tuple[RoutingRule, ...] = ()
    default_routing: DefaultRouting = field(default_factory=_default_routing_drop)
    quiet_hours_by_channel: tuple[tuple[str, QuietHours], ...] = ()
    pagerduty_routing_key: str = field(default="", repr=False)
    dashboard_url: str = ""
    otlp_endpoint: str = ""
    otlp_protocol: Literal["grpc", "http"] = "grpc"
    otlp_export_interval_seconds: int = 5
    otlp_tls: bool | None = None


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
    """LLM backend configuration (S-070, S-098, S-099).

    ``backend`` selects the concrete implementation:

    - ``""``           — LLM features disabled (default)
    - ``"llama_cpp"``  — local CPU inference via ``llama-cpp-python`` (S-070)
    - ``"ollama"``     — HTTP backend (S-098)
    - ``"cloud"``      — Anthropic/OpenAI SDK backends (S-099)

    Numeric fields apply to ``llama_cpp`` only; they are accepted on every
    config so future backends can reuse them without a schema migration.

    ``cloud_api_key`` has ``repr=False`` so ``repr(LLMConfig(...))`` never
    echoes a secret (regression-guarded by a unit test).
    """

    backend: str = ""
    model_path: str = ""
    ollama_url: str = "http://localhost:11434"
    # Ollama backend tuning (S-098). Defaults match FR-064 acceptance criteria.
    ollama_model: str = "phi4-mini"
    ollama_timeout_s: float = 30.0
    # Cloud backend tuning (S-099). ``cloud_api_key`` has ``repr=False`` so
    # ``repr(LLMConfig(...))`` never echoes a secret (mirrors
    # ``StorageConfig.postgresql_url``). The remaining fields have safe
    # defaults — empty values trigger graceful absence in the factory.
    cloud_provider: str = ""
    cloud_api_key: str = field(default="", repr=False)
    cloud_model: str = ""
    cloud_timeout_s: float = 30.0
    cloud_base_url: str = ""
    # llama_cpp tuning (S-070).
    n_ctx: int = 4096
    n_threads: int | None = None
    n_gpu_layers: int = 0
    max_tokens_default: int = 256
    temperature_default: float = 0.2
    seed: int = 42
    # Alert explanation knobs (S-071). All defaults preserve current behaviour.
    explanation_cache_size: int = 256
    explanation_cache_ttl_s: int = 3600
    explanation_max_contributing_events: int = 8
    explanation_max_prompt_chars: int = 8000
    explanation_timeout_s: float = 12.0
    # Natural language hunt knobs (S-072).
    hunt_cache_size: int = 256
    hunt_cache_ttl_s: int = 3600
    hunt_timeout_s: float = 12.0
    hunt_max_results: int = 100
    hunt_max_query_chars: int = 512
    # Sigma rule suggestion knobs (S-100, FR-066). The drafting prompt is
    # heavier than alert explanation (structured YAML output, validator
    # round-trip), so the timeout sits higher than ``explanation_timeout_s``
    # and the cache TTL is longer (operators rarely re-draft within a session).
    rule_suggestion_cache_size: int = 64
    rule_suggestion_cache_ttl_s: int = 21_600  # 6 hours
    rule_suggestion_min_tp: int = 3  # mirrors FR-066 acceptance criteria
    rule_suggestion_window_days: int = 0  # 0 = all-time
    rule_suggestion_timeout_s: float = 30.0


@dataclass(frozen=True, kw_only=True, slots=True)
class UEBASubScoreWeights:
    """Weights for the four UEBA sub-scores. Must sum to ``1.0 ± 1e-6``."""

    time_of_day: float = 0.25
    source_novelty: float = 0.30
    volume: float = 0.20
    pattern_novelty: float = 0.25


@dataclass(frozen=True, kw_only=True, slots=True)
class UEBAConfig:
    """UEBA engine configuration (FR-052/FR-053, S-064/S-065)."""

    enabled: bool = True
    warmup_days: int = 7
    warmup_min_events: int = 50
    max_entities: int = 100_000
    ema_alpha: float = 0.05
    source_ip_cap: int = 64
    template_top_k: int = 32
    # S-065 scoring fields.
    score_threshold: float = 0.75
    sub_score_weights: UEBASubScoreWeights = field(default_factory=UEBASubScoreWeights)
    alert_cooldown_seconds: int = 900


@dataclass(frozen=True, kw_only=True, slots=True)
class TAXIIAuthConfig:
    """TAXII feed credentials. All secrets sourced from env vars only."""

    kind: Literal["api_key", "basic"]
    api_key_env: str | None = None
    api_key_header: str = "Authorization"
    username_env: str | None = None
    password_env: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class TAXIIFeedConfig:
    """One TAXII 2.1 collection to poll."""

    id: str
    url: str
    collection_id: str
    poll_interval_s: int | None = None
    auth: TAXIIAuthConfig | None = None
    confidence_floor: int = 0
    enabled: bool = True
    allow_insecure: bool = False
    allow_private_addresses: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class IoCMatcherConfig:
    """Bloom-filter IoC matcher (S-068) configuration block."""

    enabled: bool = False
    fpr: float = 0.001
    min_capacity: int = 100_000
    capacity_growth_factor: float = 1.25
    confidence_floor: int = 0
    rebuild_debounce_ms: int = 200
    enabled_types: tuple[str, ...] = (
        "ipv4",
        "ipv6",
        "domain",
        "url",
        "md5",
        "sha1",
        "sha256",
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class ThreatIntelConfig:
    """Top-level threat-intelligence feed configuration."""

    enabled: bool = False
    feeds: tuple[TAXIIFeedConfig, ...] = ()
    default_poll_interval_s: int = 3600
    request_timeout_s: float = 30.0
    max_indicators_per_feed: int = 1_000_000
    expired_grace_days: int = 30
    startup_jitter_s: int = 30
    matcher: IoCMatcherConfig = field(default_factory=IoCMatcherConfig)


@dataclass(frozen=True, kw_only=True, slots=True)
class SeerflowConfig:
    """Top-level Seerflow configuration."""

    storage: StorageConfig = field(default_factory=StorageConfig)
    receivers: ReceiverConfig = field(default_factory=ReceiverConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    ueba: UEBAConfig = field(default_factory=UEBAConfig)
    threat_intel: ThreatIntelConfig = field(default_factory=ThreatIntelConfig)
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
    _build_ueba as _build_ueba,
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

    from seerflow._config_validation import validate_seerflow_config
    from seerflow._threat_intel_builders import _build_threat_intel_config

    threat_intel = _build_threat_intel_config(raw.get("threat_intel", {}))

    cfg = SeerflowConfig(
        storage=_build_storage(raw.get("storage", {})),
        receivers=_build_receivers(raw.get("receivers", {})),
        detection=_build_detection(raw.get("detection", {})),
        correlation=_build_correlation(raw.get("correlation", {})),
        alerting=_build_alerting(raw.get("alerting", {})),
        llm=_build_llm(raw.get("llm", {})),
        ueba=_build_ueba(raw.get("ueba", {})),
        threat_intel=threat_intel,
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

    validate_seerflow_config(cfg)
    return cfg
