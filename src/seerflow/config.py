"""YAML config loader with ``${ENV_VAR:-default}`` interpolation.

Config is loaded once at startup. Every component reads from the resulting
``SeerflowConfig`` instance. If no config file is found, sensible defaults
are used (zero-config first run per NFR-006).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    postgresql_url: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class WebhookEndpointConfig:
    """Configuration for a single webhook endpoint (YAML-loadable)."""

    path: str = "/ingest/webhook"
    auth_header: str = ""
    auth_token: str = ""
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
    markov_smoothing: float = 1e-6
    markov_min_events: int = 100
    markov_max_entities: int = 1000
    weights_content: float = 0.30
    weights_volume: float = 0.25
    weights_sequence: float = 0.25
    weights_pattern: float = 0.20


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertingConfig:
    """Alert routing configuration."""

    dedup_window_seconds: int = 900
    webhooks: tuple[dict[str, Any], ...] = ()
    pagerduty_routing_key: str = ""


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
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    dashboard_port: int = 8080
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


def _build_receivers(data: dict[str, Any]) -> ReceiverConfig:
    file_paths = data.get("file_paths", ())
    if isinstance(file_paths, list):
        file_paths = tuple(file_paths)
    allowed_log_roots = data.get("allowed_log_roots", ())
    if isinstance(allowed_log_roots, list):
        allowed_log_roots = tuple(allowed_log_roots)
    raw_webhooks = data.get("webhooks", ())
    if isinstance(raw_webhooks, list):
        webhook_configs: list[WebhookEndpointConfig] = []
        for wh in raw_webhooks:
            if not isinstance(wh, dict):
                msg = "Each webhook entry must be a mapping"
                raise ConfigError(msg)
            fm = wh.get("field_mapping", {})
            if isinstance(fm, dict):
                fm = {str(k): str(v) for k, v in fm.items()}
            webhook_configs.append(
                WebhookEndpointConfig(
                    path=wh.get("path", "/ingest/webhook"),
                    auth_header=wh.get("auth_header", ""),
                    auth_token=wh.get("auth_token", ""),
                    field_mapping=fm,
                    source_id=wh.get("source_id", "webhook"),
                )
            )
        webhooks_tuple = tuple(webhook_configs)
    else:
        webhooks_tuple = ()
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
        webhooks=webhooks_tuple,
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
    return cfg


def _build_detection(data: dict[str, Any]) -> DetectionConfig:
    dspot = data.get("dspot", {})
    return DetectionConfig(
        hst_window_size=data.get("hst_window_size", 1000),
        hst_n_trees=data.get("hst_n_trees", 25),
        dspot_calibration_window=dspot.get("calibration_window", 1000),
        dspot_risk_level=dspot.get("risk_level", 0.0001),
        dspot_initial_percentile=dspot.get("initial_percentile", 98),
        hw_seasonal_period=data.get("hw_seasonal_period", 1440),
        hw_alpha=data.get("hw_alpha", 0.3),
        hw_beta=data.get("hw_beta", 0.1),
        hw_gamma=data.get("hw_gamma", 0.1),
        hw_n_std=data.get("hw_n_std", 3.0),
        cusum_drift=data.get("cusum_drift", 0.5),
        cusum_threshold=data.get("cusum_threshold", 5.0),
        markov_smoothing=data.get("markov_smoothing", 1e-6),
        markov_min_events=data.get("markov_min_events", 100),
        markov_max_entities=data.get("markov_max_entities", 1000),
        weights_content=data.get("weights_content", 0.30),
        weights_volume=data.get("weights_volume", 0.25),
        weights_sequence=data.get("weights_sequence", 0.25),
        weights_pattern=data.get("weights_pattern", 0.20),
    )


def _build_alerting(data: dict[str, Any]) -> AlertingConfig:
    webhooks = data.get("webhooks", ())
    if isinstance(webhooks, list):
        webhooks = tuple(webhooks)
    return AlertingConfig(
        dedup_window_seconds=data.get("dedup_window_seconds", 900),
        webhooks=webhooks,
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


def load_config(
    path: str | None = None,
    *,
    search_dir: Path | None = None,
) -> SeerflowConfig:
    """Load Seerflow configuration from a YAML file.

    Args:
        path: Explicit path to a YAML config file. If the file does not
            exist, raises ``ConfigError``. If ``None``, searches for
            ``seerflow.yaml`` in *search_dir* (default: CWD).
        search_dir: Directory to search for ``seerflow.yaml`` when *path*
            is ``None``. Defaults to the current working directory.

    Returns:
        A frozen ``SeerflowConfig`` with all env vars resolved.

    Raises:
        ConfigError: If a required ``${VAR}`` env var is not set, the
            config file is malformed, or an explicit path does not exist.
    """
    raw: dict[str, Any] = {}

    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {path}")
        try:
            with config_path.open() as f:
                raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse config file {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"Config file must be a YAML mapping, got {type(raw).__name__}")
    else:
        search = search_dir or Path.cwd()
        candidate = search / "seerflow.yaml"
        if candidate.exists():
            try:
                with candidate.open() as f:
                    raw = yaml.safe_load(f) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(f"Failed to parse config file {candidate}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ConfigError(f"Config file must be a YAML mapping, got {type(raw).__name__}")

    # Interpolate env vars in all string values
    raw = _walk_and_interpolate(raw)

    log_level = raw.get("log_level", "INFO")
    if log_level not in _VALID_LOG_LEVELS:
        raise ConfigError(
            f"Invalid log_level {log_level!r}. Must be one of {sorted(_VALID_LOG_LEVELS)}"
        )

    dashboard_port = raw.get("dashboard_port", 8080)
    _require_valid_port("dashboard_port", dashboard_port)

    return SeerflowConfig(
        storage=_build_storage(raw.get("storage", {})),
        receivers=_build_receivers(raw.get("receivers", {})),
        detection=_build_detection(raw.get("detection", {})),
        alerting=_build_alerting(raw.get("alerting", {})),
        llm=_build_llm(raw.get("llm", {})),
        dashboard_port=dashboard_port,
        log_level=log_level,
    )
