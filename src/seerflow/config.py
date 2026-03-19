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

_DEFAULT_DATA_DIR = str(Path.home() / ".local" / "share" / "seerflow")


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
class ReceiverConfig:
    """Log receiver configuration."""

    syslog_enabled: bool = True
    syslog_udp_port: int = 514
    syslog_tcp_port: int = 601
    otlp_grpc_enabled: bool = True
    otlp_grpc_port: int = 4317
    otlp_http_enabled: bool = True
    otlp_http_port: int = 4318
    file_paths: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class DetectionConfig:
    """ML detection configuration."""

    hst_window_size: int = 1000
    hst_n_trees: int = 25
    dspot_calibration_window: int = 1000
    dspot_risk_level: float = 0.0001
    weights_content: float = 0.30
    weights_volume: float = 0.25
    weights_sequence: float = 0.25
    weights_pattern: float = 0.20


@dataclass(frozen=True, kw_only=True, slots=True)
class AlertingConfig:
    """Alert routing configuration."""

    dedup_window_seconds: int = 900
    webhooks: tuple[dict[str, str], ...] = ()
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
    """Recursively walk a dict/list structure and interpolate env vars in strings."""
    if isinstance(obj, str):
        return _interpolate_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_interpolate(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return tuple(_walk_and_interpolate(item) for item in obj)
    return obj


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Section constructors
# ---------------------------------------------------------------------------


def _build_storage(data: dict[str, Any]) -> StorageConfig:
    data_dir = data.get("data_dir") or os.environ.get("SEERFLOW_DATA_DIR") or _DEFAULT_DATA_DIR
    sqlite_path = data.get("sqlite_path") or str(Path(data_dir) / "seerflow.db")
    return StorageConfig(
        backend=data.get("backend", "sqlite"),
        data_dir=data_dir,
        sqlite_path=sqlite_path,
        postgresql_url=data.get("postgresql_url", ""),
    )


def _build_receivers(data: dict[str, Any]) -> ReceiverConfig:
    file_paths = data.get("file_paths", ())
    if isinstance(file_paths, list):
        file_paths = tuple(file_paths)
    return ReceiverConfig(
        syslog_enabled=data.get("syslog_enabled", True),
        syslog_udp_port=data.get("syslog_udp_port", 514),
        syslog_tcp_port=data.get("syslog_tcp_port", 601),
        otlp_grpc_enabled=data.get("otlp_grpc_enabled", True),
        otlp_grpc_port=data.get("otlp_grpc_port", 4317),
        otlp_http_enabled=data.get("otlp_http_enabled", True),
        otlp_http_port=data.get("otlp_http_port", 4318),
        file_paths=file_paths,
    )


def _build_detection(data: dict[str, Any]) -> DetectionConfig:
    dspot = data.get("dspot", {})
    return DetectionConfig(
        hst_window_size=data.get("hst_window_size", 1000),
        hst_n_trees=data.get("hst_n_trees", 25),
        dspot_calibration_window=dspot.get(
            "calibration_window", data.get("dspot_calibration_window", 1000)
        ),
        dspot_risk_level=dspot.get("risk_level", data.get("dspot_risk_level", 0.0001)),
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
        path: Explicit path to a YAML config file. If ``None``, searches
            for ``seerflow.yaml`` in *search_dir* (default: CWD).
        search_dir: Directory to search for ``seerflow.yaml`` when *path*
            is ``None``. Defaults to the current working directory.

    Returns:
        A frozen ``SeerflowConfig`` with all env vars resolved.

    Raises:
        ConfigError: If a required ``${VAR}`` env var is not set.
    """
    raw: dict[str, Any] = {}

    if path is not None:
        config_path = Path(path)
        if config_path.exists():
            with config_path.open() as f:
                raw = yaml.safe_load(f) or {}
    else:
        search = search_dir or Path.cwd()
        candidate = search / "seerflow.yaml"
        if candidate.exists():
            with candidate.open() as f:
                raw = yaml.safe_load(f) or {}

    # Interpolate env vars in all string values
    raw = _walk_and_interpolate(raw)

    return SeerflowConfig(
        storage=_build_storage(raw.get("storage", {})),
        receivers=_build_receivers(raw.get("receivers", {})),
        detection=_build_detection(raw.get("detection", {})),
        alerting=_build_alerting(raw.get("alerting", {})),
        llm=_build_llm(raw.get("llm", {})),
        dashboard_port=raw.get("dashboard_port", 8080),
        log_level=raw.get("log_level", "INFO"),
    )
