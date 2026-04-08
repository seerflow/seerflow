"""YAML config loader with ``${ENV_VAR:-default}`` interpolation.

Config is loaded once at startup. Every component reads from the resulting
``SeerflowConfig`` instance. If no config file is found, sensible defaults
are used (zero-config first run per NFR-006).
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seerflow.alerting.dispatcher import WebhookTarget

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_STORAGE_BACKENDS = frozenset({"sqlite", "postgresql"})


def _default_data_dir() -> str:
    """Compute XDG-compliant default data directory (lazy, respects $XDG_DATA_HOME)."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(xdg_data_home) / "seerflow")


class ConfigError(Exception):
    """Raised when configuration is invalid or a required env var is missing."""


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


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertingConfig:
    """Alert routing configuration."""

    dedup_window_seconds: int = 900
    dedup_window_overrides: tuple[tuple[str, int], ...] = ()
    webhooks: tuple[dict[str, Any], ...] = ()
    webhook_targets: tuple[WebhookTarget, ...] = ()
    pagerduty_routing_key: str = field(default="", repr=False)
    dashboard_url: str = ""


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


# ---------------------------------------------------------------------------
# Env var interpolation
# ---------------------------------------------------------------------------


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
# Validation helpers
# ---------------------------------------------------------------------------


def _require_valid_port(name: str, value: int) -> None:
    if not (1 <= value <= 65535):
        raise ConfigError(f"{name} must be between 1 and 65535, got {value!r}")


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


def _require_finite_positive(field: str, value: float) -> None:
    """Raise ConfigError if *value* is not finite or not > 0."""
    if not math.isfinite(value) or value <= 0.0:
        raise ConfigError(f"{field} must be finite and > 0, got {value!r}")


def _require_open_unit(field: str, value: float) -> None:
    """Raise ConfigError if *value* is not in the open interval (0, 1)."""
    if not (0.0 < value < 1.0):
        raise ConfigError(f"{field} must be in (0, 1), got {value!r}")


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


def _build_alerting(data: dict[str, Any]) -> AlertingConfig:
    webhooks = data.get("webhooks", ())
    if isinstance(webhooks, list):
        webhooks = tuple(webhooks)
    raw_overrides = data.get("dedup_window_overrides", {})
    overrides: tuple[tuple[str, int], ...] = ()
    if isinstance(raw_overrides, dict):
        parsed: list[tuple[str, int]] = []
        for k, v in raw_overrides.items():
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
        overrides = tuple(parsed)
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
    return AlertingConfig(
        dedup_window_seconds=dedup_window_seconds,
        dedup_window_overrides=overrides,
        webhooks=webhooks,
        webhook_targets=webhook_targets,
        pagerduty_routing_key=data.get("pagerduty_routing_key", ""),
    )


def _build_llm(data: dict[str, Any]) -> LLMConfig:
    return LLMConfig(
        backend=data.get("backend", ""),
        model_path=data.get("model_path", ""),
        ollama_url=data.get("ollama_url", "http://localhost:11434"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    )
