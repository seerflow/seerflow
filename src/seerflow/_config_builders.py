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
from typing import TYPE_CHECKING, Any, Literal, NamedTuple
from urllib.parse import urlparse

import yaml

from seerflow._config_validation import (
    _VALID_GRAPH_BACKENDS,
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
    UEBAConfig,
    UEBASubScoreWeights,
    WebhookEndpointConfig,
)

if TYPE_CHECKING:
    from datetime import time

    from seerflow.alerting.dispatcher import WebhookTarget
    from seerflow.alerting.router import DefaultRouting, QuietHours, RoutingRule, RoutingRuleNotify


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
    # S-074: DSN must be non-empty when backend=postgresql. Fail at
    # config-load so the operator sees the error in their YAML feedback
    # loop, not at ``connect_storage`` time after process start-up.
    postgresql_url = data.get("postgresql_url", "")
    if backend == "postgresql" and not str(postgresql_url).strip():
        msg = (
            "storage.postgresql_url is required when storage.backend is "
            "'postgresql' (set it in YAML, e.g. "
            "postgresql_url: ${SEERFLOW_PG_URL})"
        )
        raise ConfigError(msg)
    # S-073: asyncpg pool knobs. Defaults match ``StorageConfig``;
    # validation runs unconditionally so an invalid value in the YAML
    # surfaces even when ``backend == "sqlite"`` (operators sometimes
    # toggle the backend without re-reading the pool block).
    pool_min_size = data.get("postgresql_pool_min_size", 2)
    pool_max_size = data.get("postgresql_pool_max_size", 10)
    command_timeout_s = data.get("postgresql_command_timeout_s", 30.0)
    _validate_postgres_pool(pool_min_size, pool_max_size, command_timeout_s)
    # S-155: graph backend selector. Validated at config-load so a typo
    # surfaces in the YAML feedback loop, not at ``connect_graph`` time.
    graph_backend = data.get("graph_backend", "igraph")
    if graph_backend not in _VALID_GRAPH_BACKENDS:
        valid_graph = sorted(_VALID_GRAPH_BACKENDS)
        msg = f"Invalid storage.graph_backend {graph_backend!r}. Must be one of {valid_graph}"
        raise ConfigError(msg)
    return StorageConfig(
        backend=backend,
        data_dir=data_dir,
        sqlite_path=sqlite_path,
        postgresql_url=postgresql_url,
        postgresql_pool_min_size=int(pool_min_size),
        postgresql_pool_max_size=int(pool_max_size),
        postgresql_command_timeout_s=float(command_timeout_s),
        graph_backend=graph_backend,
    )


def _validate_postgres_pool(
    min_size: object,
    max_size: object,
    command_timeout_s: object,
) -> None:
    """Validate asyncpg connection-pool knobs.

    All three checks run before ``StorageConfig`` is constructed so the
    error message identifies the offending field rather than the dataclass
    coercion failure.
    """
    if not isinstance(min_size, int) or isinstance(min_size, bool) or min_size < 1:
        msg = f"storage.postgresql_pool_min_size must be a positive integer >= 1, got {min_size!r}"
        raise ConfigError(msg)
    if not isinstance(max_size, int) or isinstance(max_size, bool) or max_size < min_size:
        msg = (
            f"storage.postgresql_pool_max_size must be a positive integer >= "
            f"postgresql_pool_min_size ({min_size}), got {max_size!r}"
        )
        raise ConfigError(msg)
    if (
        not isinstance(command_timeout_s, int | float)
        or isinstance(command_timeout_s, bool)
        or command_timeout_s <= 0
    ):
        msg = (
            f"storage.postgresql_command_timeout_s must be a positive number, "
            f"got {command_timeout_s!r}"
        )
        raise ConfigError(msg)


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

# Reject any header-like field (email From/To/Subject) containing CR/LF —
# such characters can split SMTP headers on relays that do not enforce
# Python 3 ``email.message.EmailMessage`` folding semantics.
_HEADER_INJECTION_RE = re.compile(r"[\r\n]")


def _build_webhook_targets(raw_webhooks: tuple[dict[str, Any], ...]) -> tuple[WebhookTarget, ...]:
    """Parse raw webhook dicts into a tuple of WebhookTarget objects."""
    from seerflow.alerting.dispatcher import WebhookTarget

    targets: list[WebhookTarget] = []
    used_names: set[str] = set()
    for idx, wh in enumerate(raw_webhooks):
        url = wh.get("url", "")
        if not url:
            raise ConfigError("alerting.webhooks[*].url must be a non-empty string")
        _parsed = urlparse(url)
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
        name = wh.get("name") or f"webhook-{idx}"
        if not isinstance(name, str) or not name:
            raise ConfigError(f"alerting.webhooks[{idx}].name must be a non-empty string")
        if name in used_names:
            raise ConfigError(f"alerting.webhooks: duplicate name {name!r}")
        used_names.add(name)
        targets.append(WebhookTarget(name=name, url=url, format=fmt, min_severity=min_severity))
    return tuple(targets)


def _build_email_targets(raw: tuple[dict[str, Any], ...]) -> tuple[Any, ...]:
    from seerflow.alerting.channels.email import EmailTarget

    targets: list[EmailTarget] = []
    used: set[str] = set()
    for idx, e in enumerate(raw):
        name = e.get("name") or f"email-{idx}"
        if not isinstance(name, str) or not name:
            raise ConfigError(f"alerting.email_targets[{idx}].name must be non-empty string")
        if name in used:
            raise ConfigError(f"alerting.email_targets: duplicate name {name!r}")
        used.add(name)
        host = e.get("smtp_host", "")
        if not isinstance(host, str) or not host:
            raise ConfigError(f"alerting.email_targets[{idx}].smtp_host required")
        if _is_private_ip(host):
            raise ConfigError(
                f"alerting.email_targets[{idx}].smtp_host must not be private: {host}"
            )
        port = e.get("smtp_port", 587)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ConfigError(f"alerting.email_targets[{idx}].smtp_port must be 1..65535")
        to_raw = e.get("to_addresses") or []
        if (
            not isinstance(to_raw, list)
            or not to_raw
            or not all(isinstance(a, str) and a for a in to_raw)
            or any(_HEADER_INJECTION_RE.search(a) for a in to_raw)
        ):
            raise ConfigError(
                f"alerting.email_targets[{idx}].to_addresses must be non-empty"
                " list[str] with no newline characters"
            )
        to_addresses = tuple(to_raw)
        from_address = str(e.get("from_address", ""))
        if _HEADER_INJECTION_RE.search(from_address):
            raise ConfigError(
                f"alerting.email_targets[{idx}].from_address must not contain newline characters"
            )
        max_per_minute = e.get("max_per_minute")
        if max_per_minute is not None and (
            not isinstance(max_per_minute, int)
            or isinstance(max_per_minute, bool)
            or max_per_minute < 1
        ):
            raise ConfigError(f"alerting.email_targets[{idx}].max_per_minute must be int >= 1")
        min_sev = e.get("min_severity", 0)
        if not isinstance(min_sev, int) or isinstance(min_sev, bool) or not 0 <= min_sev <= 6:
            raise ConfigError(f"alerting.email_targets[{idx}].min_severity must be int in [0,6]")
        smtp_password = str(e.get("smtp_password", ""))
        use_starttls = bool(e.get("use_starttls", True))
        # Reject any config that would send smtp_password over a plaintext
        # connection. Port 465 is the implicit-TLS SMTP port — allow it as a
        # future exception once the target is extended to honour use_tls.
        if smtp_password and not use_starttls and port != 465:
            raise ConfigError(
                f"alerting.email_targets[{idx}]: smtp_password set with"
                " use_starttls=false on non-implicit-TLS port — refusing to"
                " send credentials over plaintext"
            )
        targets.append(
            EmailTarget(
                name=name,
                smtp_host=host,
                smtp_port=port,
                use_starttls=use_starttls,
                from_address=from_address,
                to_addresses=to_addresses,
                smtp_user=str(e.get("smtp_user", "")),
                smtp_password=smtp_password,
                min_severity=min_sev,
                max_per_minute=max_per_minute,
            )
        )
    return tuple(targets)


def _build_sms_targets(raw: tuple[dict[str, Any], ...]) -> tuple[Any, ...]:
    from seerflow.alerting.channels.sms import SmsTarget

    targets: list[SmsTarget] = []
    used: set[str] = set()
    for idx, s in enumerate(raw):
        provider = s.get("provider", "twilio")
        if provider != "twilio":
            raise ConfigError(
                f"alerting.sms_targets[{idx}].provider: only 'twilio' supported, got {provider!r}"
            )
        name = s.get("name") or f"sms-{idx}"
        if not isinstance(name, str) or not name:
            raise ConfigError(f"alerting.sms_targets[{idx}].name must be non-empty string")
        if name in used:
            raise ConfigError(f"alerting.sms_targets: duplicate name {name!r}")
        used.add(name)
        to_raw = s.get("to_numbers") or []
        if (
            not isinstance(to_raw, list)
            or not to_raw
            or not all(isinstance(n, str) and n for n in to_raw)
        ):
            raise ConfigError(
                f"alerting.sms_targets[{idx}].to_numbers must be non-empty list[str]"
            )
        min_sev = s.get("min_severity", 0)
        if not isinstance(min_sev, int) or isinstance(min_sev, bool) or not 0 <= min_sev <= 6:
            raise ConfigError(f"alerting.sms_targets[{idx}].min_severity must be int in [0,6]")
        rate = s.get("rate_per_second", 1.0)
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            raise ConfigError(
                f"alerting.sms_targets[{idx}].rate_per_second must be positive number"
            )
        burst = s.get("burst", 3)
        if not isinstance(burst, int) or isinstance(burst, bool) or burst < 1:
            raise ConfigError(f"alerting.sms_targets[{idx}].burst must be int >= 1")
        targets.append(
            SmsTarget(
                name=name,
                account_sid=str(s.get("account_sid", "")),
                auth_token=str(s.get("auth_token", "")),
                from_number=str(s.get("from_number", "")),
                to_numbers=tuple(to_raw),
                min_severity=min_sev,
                rate_per_second=float(rate),
                burst=int(burst),
            )
        )
    return tuple(targets)


def _build_telegram_targets(raw: tuple[dict[str, Any], ...]) -> tuple[Any, ...]:
    from seerflow.alerting.channels.telegram import TelegramTarget

    targets: list[TelegramTarget] = []
    used: set[str] = set()
    for idx, t in enumerate(raw):
        name = t.get("name") or f"telegram-{idx}"
        if not isinstance(name, str) or not name:
            raise ConfigError(f"alerting.telegram_targets[{idx}].name must be non-empty string")
        if name in used:
            raise ConfigError(f"alerting.telegram_targets: duplicate name {name!r}")
        used.add(name)
        token = str(t.get("bot_token", ""))
        if not token:
            raise ConfigError(f"alerting.telegram_targets[{idx}].bot_token required")
        chat_id = str(t.get("chat_id", ""))
        if not chat_id:
            raise ConfigError(f"alerting.telegram_targets[{idx}].chat_id required")
        min_sev = t.get("min_severity", 0)
        if not isinstance(min_sev, int) or isinstance(min_sev, bool) or not 0 <= min_sev <= 6:
            raise ConfigError(
                f"alerting.telegram_targets[{idx}].min_severity must be int in [0,6]"
            )
        rate = t.get("rate_per_second", 30.0)
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            raise ConfigError(f"alerting.telegram_targets[{idx}].rate_per_second must be positive")
        burst = t.get("burst", 30)
        if not isinstance(burst, int) or isinstance(burst, bool) or burst < 1:
            raise ConfigError(f"alerting.telegram_targets[{idx}].burst must be int >= 1")
        targets.append(
            TelegramTarget(
                name=name,
                bot_token=token,
                chat_id=chat_id,
                min_severity=min_sev,
                rate_per_second=float(rate),
                burst=int(burst),
            )
        )
    return tuple(targets)


def _build_whatsapp_targets(raw: tuple[dict[str, Any], ...]) -> tuple[Any, ...]:
    from seerflow.alerting.channels.whatsapp import WhatsAppTarget

    targets: list[WhatsAppTarget] = []
    used: set[str] = set()
    for idx, w in enumerate(raw):
        name = w.get("name") or f"whatsapp-{idx}"
        if not isinstance(name, str) or not name:
            raise ConfigError(f"alerting.whatsapp_targets[{idx}].name must be non-empty string")
        if name in used:
            raise ConfigError(f"alerting.whatsapp_targets: duplicate name {name!r}")
        used.add(name)
        to_raw = w.get("to_numbers") or []
        if (
            not isinstance(to_raw, list)
            or not to_raw
            or not all(isinstance(n, str) and n for n in to_raw)
        ):
            raise ConfigError(
                f"alerting.whatsapp_targets[{idx}].to_numbers must be non-empty list[str]"
            )
        min_sev = w.get("min_severity", 0)
        if not isinstance(min_sev, int) or isinstance(min_sev, bool) or not 0 <= min_sev <= 6:
            raise ConfigError(
                f"alerting.whatsapp_targets[{idx}].min_severity must be int in [0,6]"
            )
        rate = w.get("rate_per_second", 10.0)
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
            raise ConfigError(f"alerting.whatsapp_targets[{idx}].rate_per_second must be positive")
        burst = w.get("burst", 20)
        if not isinstance(burst, int) or isinstance(burst, bool) or burst < 1:
            raise ConfigError(f"alerting.whatsapp_targets[{idx}].burst must be int >= 1")
        targets.append(
            WhatsAppTarget(
                name=name,
                phone_number_id=str(w.get("phone_number_id", "")),
                access_token=str(w.get("access_token", "")),
                template_name=str(w.get("template_name", "seerflow_alert")),
                language_code=str(w.get("language_code", "en")),
                to_numbers=tuple(to_raw),
                min_severity=min_sev,
                rate_per_second=float(rate),
                burst=int(burst),
            )
        )
    return tuple(targets)


def _parse_hhmm(value: str, label: str) -> time:
    from datetime import time as _time

    try:
        hh, mm = value.split(":", 1)
        return _time(int(hh), int(mm))
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{label} must be HH:MM, got {value!r}") from exc


def _build_quiet_hours(raw: dict[str, Any], channel: str) -> QuietHours:
    from seerflow.alerting.router import QuietHours

    start = _parse_hhmm(str(raw.get("start", "")), f"alerting.{channel}.quiet_hours.start")
    end = _parse_hhmm(str(raw.get("end", "")), f"alerting.{channel}.quiet_hours.end")
    if start == end:
        raise ConfigError(
            f"alerting.{channel}.quiet_hours.end must differ from start (got {start})"
        )
    min_sev = raw.get("min_severity", 0)
    if not isinstance(min_sev, int) or isinstance(min_sev, bool) or not 0 <= min_sev <= 6:
        raise ConfigError(f"alerting.{channel}.quiet_hours.min_severity must be an int in [0,6]")
    return QuietHours(start=start, end=end, min_severity=min_sev)


def _normalise_str_or_list(v: object, label: str) -> str | tuple[str, ...] | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return tuple(v)
    raise ConfigError(f"{label} must be str or list[str], got {v!r}")


def _severity_bound(v: object, label: str) -> int | None:
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 6:
        raise ConfigError(f"{label} must be int in [0,6], got {v!r}")
    return v


def _build_notify_entry(
    n: dict[str, Any], known_channels: set[str], label: str
) -> RoutingRuleNotify:
    from seerflow.alerting.router import RoutingRuleNotify

    channel = n.get("channel", "")
    if channel not in known_channels:
        raise ConfigError(f"{label}: unknown channel {channel!r}")
    mode = n.get("mode", "immediate")
    if mode not in ("immediate", "digest"):
        raise ConfigError(f"{label}.mode must be immediate|digest, got {mode!r}")
    window = n.get("digest_window_minutes", 15)
    # Upper bound caps the flusher sleep + buffer growth window to a day.
    if not isinstance(window, int) or isinstance(window, bool) or window < 1 or window > 1440:
        raise ConfigError(f"{label}.digest_window_minutes must be int in [1, 1440]")
    return RoutingRuleNotify(channel=channel, mode=mode, digest_window_minutes=window)


def _build_routing_rule(idx: int, entry: dict[str, Any], known_channels: set[str]) -> RoutingRule:
    from seerflow.alerting.router import RoutingRule, RoutingRuleMatch

    match_raw = entry.get("match", {}) or {}
    min_sev = _severity_bound(
        match_raw.get("min_severity"), f"routing_rules[{idx}].match.min_severity"
    )
    max_sev = _severity_bound(
        match_raw.get("max_severity"), f"routing_rules[{idx}].match.max_severity"
    )
    if min_sev is not None and max_sev is not None and min_sev > max_sev:
        raise ConfigError(
            f"routing_rules[{idx}]: min_severity ({min_sev}) > max_severity ({max_sev})"
        )
    rule_name_raw = match_raw.get("rule_name")
    if rule_name_raw is not None and not isinstance(rule_name_raw, str):
        raise ConfigError(
            f"routing_rules[{idx}].match.rule_name must be a string glob,"
            f" got {type(rule_name_raw).__name__}"
        )
    match = RoutingRuleMatch(
        alert_type=_normalise_str_or_list(
            match_raw.get("alert_type"), f"routing_rules[{idx}].match.alert_type"
        ),
        rule_name=rule_name_raw,
        entity_type=_normalise_str_or_list(
            match_raw.get("entity_type"), f"routing_rules[{idx}].match.entity_type"
        ),
        min_severity=min_sev,
        max_severity=max_sev,
    )
    notify_list = [
        _build_notify_entry(n, known_channels, f"routing_rules[{idx}].notify[{n_idx}]")
        for n_idx, n in enumerate(entry.get("notify", []) or [])
    ]
    return RoutingRule(match=match, notify=tuple(notify_list))


def _build_routing_rules(raw: object, known_channels: set[str]) -> tuple[RoutingRule, ...]:
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("alerting.routing_rules must be a list")
    return tuple(_build_routing_rule(idx, entry, known_channels) for idx, entry in enumerate(raw))


def _build_default_routing(
    raw: object, known_channels: set[str], has_rules: bool
) -> DefaultRouting:
    from seerflow.alerting.router import DefaultRouting

    if not raw:
        return DefaultRouting(action="drop")
    if not isinstance(raw, dict):
        raise ConfigError("alerting.default_routing must be a mapping")
    if not has_rules:
        raise ConfigError("alerting.default_routing requires routing_rules to also be configured")
    action = raw.get("action", "drop")
    if action not in ("drop", "notify"):
        raise ConfigError(f"alerting.default_routing.action must be drop|notify, got {action!r}")
    notify_list = [
        _build_notify_entry(n, known_channels, f"alerting.default_routing.notify[{n_idx}]")
        for n_idx, n in enumerate(raw.get("notify", []) or [])
    ]
    if action == "notify" and not notify_list:
        raise ConfigError(
            "alerting.default_routing.action=notify requires a non-empty notify list"
        )
    return DefaultRouting(action=action, notify=tuple(notify_list))


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


def _validate_dedup_window(data: dict[str, Any]) -> int:
    value = data.get("dedup_window_seconds", 900)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"alerting.dedup_window_seconds must be an integer >= 1, got {value!r}")
    return value


def _validate_dashboard_url_field(data: dict[str, Any]) -> str:
    url = data.get("dashboard_url", "")
    if not isinstance(url, str):
        raise ConfigError(f"alerting.dashboard_url must be a string, got {type(url).__name__}")
    if url:
        _validate_dashboard_url(url)
    return url


def _validate_pagerduty_key(data: dict[str, Any]) -> str:
    key = data.get("pagerduty_routing_key", "")
    if key and not re.fullmatch(r"[0-9a-fA-F]{32}", key):
        raise ConfigError("alerting.pagerduty_routing_key must be a 32-character hex string")
    return str(key)


class _OtlpFields(NamedTuple):
    """Validated OTLP-export settings extracted from ``alerting`` YAML (S-049b).

    Introduced when S-049b added three new path fields, pushing the previous
    4-tuple over the tasteful return-tuple ceiling. Internal to the builder
    module — callers go through :func:`_build_alerting` and read fields off
    :class:`AlertingConfig`.
    """

    endpoint: str
    protocol: Literal["grpc", "http"]
    interval: int
    tls: bool | None
    tls_ca_file: str
    mtls_cert_file: str
    mtls_key_file: str


def _validate_otlp_str_path(field_name: str, value: Any) -> str:
    """Validate that a YAML value is a string (path-shaped). Empty allowed.

    Path readability is enforced separately by
    :func:`_validate_readable_pem_path` so type errors surface before any
    file-system I/O.
    """
    if not isinstance(value, str):
        raise ConfigError(f"alerting.{field_name} must be a string, got {type(value).__name__}")
    return value


def _validate_readable_pem_path(field_name: str, path: str) -> None:
    """Confirm a non-empty PEM path exists and is readable as bytes.

    Empty paths are accepted (no-op) — they signal "no custom CA / no mTLS"
    in the OTLP sink. Otherwise we open the file with
    :meth:`pathlib.Path.read_bytes` so directories, missing files, and
    permission errors all surface as :class:`ConfigError` with the field
    name and path included.

    Path content is NOT parsed here. PEM validity is enforced by the gRPC
    stack at handshake time — surfacing a corrupted-PEM error at startup
    would require pulling in ``cryptography`` for a side-effect-only
    smoke parse, which is heavier than the bug it prevents.
    """
    if not path:
        return
    try:
        Path(path).read_bytes()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as exc:
        raise ConfigError(f"alerting.{field_name}: cannot read {path!r}: {exc}") from exc


def _validate_otlp_settings(data: dict[str, Any]) -> _OtlpFields:
    endpoint = data.get("otlp_endpoint", "")
    if not isinstance(endpoint, str):
        raise ConfigError(
            f"alerting.otlp_endpoint must be a string, got {type(endpoint).__name__}"
        )
    if endpoint and "://" in endpoint:
        parsed_ep = urlparse(endpoint)
        if parsed_ep.scheme not in {"http", "https"}:
            raise ConfigError(
                f"alerting.otlp_endpoint: unsupported scheme {parsed_ep.scheme!r},"
                " expected http, https, or bare host:port"
            )
    protocol = data.get("otlp_protocol", "grpc")
    if protocol not in ("grpc", "http"):
        raise ConfigError(f"alerting.otlp_protocol must be 'grpc' or 'http', got {protocol!r}")
    interval = data.get("otlp_export_interval_seconds", 5)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise ConfigError(
            f"alerting.otlp_export_interval_seconds must be an integer >= 1, got {interval!r}"
        )
    tls_raw = data.get("otlp_tls")
    if tls_raw is not None and not isinstance(tls_raw, bool):
        raise ConfigError(
            f"alerting.otlp_tls must be a boolean or null, got {type(tls_raw).__name__}"
        )
    # S-049b: custom CA bundle + mTLS file paths. Type-validate first, then
    # readability-check each non-empty path so config-load fails fast with a
    # clear message instead of a cryptic TLS handshake failure later.
    tls_ca_file = _validate_otlp_str_path("otlp_tls_ca_file", data.get("otlp_tls_ca_file", ""))
    mtls_cert_file = _validate_otlp_str_path(
        "otlp_mtls_cert_file", data.get("otlp_mtls_cert_file", "")
    )
    mtls_key_file = _validate_otlp_str_path(
        "otlp_mtls_key_file", data.get("otlp_mtls_key_file", "")
    )
    _validate_readable_pem_path("otlp_tls_ca_file", tls_ca_file)
    _validate_readable_pem_path("otlp_mtls_cert_file", mtls_cert_file)
    _validate_readable_pem_path("otlp_mtls_key_file", mtls_key_file)
    # Partial mTLS is a config error — grpc.ssl_channel_credentials pairs
    # certificate_chain and private_key, so accepting one without the other
    # would produce a cryptic handshake failure at first send instead of a
    # clear startup error. CA-only (no client cert) remains valid.
    if bool(mtls_cert_file) != bool(mtls_key_file):
        raise ConfigError(
            "alerting.otlp_mtls_cert_file and alerting.otlp_mtls_key_file "
            "must both be set or both be empty"
        )
    return _OtlpFields(
        endpoint=endpoint,
        protocol=protocol,
        interval=interval,
        tls=tls_raw,
        tls_ca_file=tls_ca_file,
        mtls_cert_file=mtls_cert_file,
        mtls_key_file=mtls_key_file,
    )


def _collect_quiet_hours(
    webhooks: tuple[dict[str, Any], ...],
    targets: tuple[WebhookTarget, ...],
) -> tuple[tuple[str, QuietHours], ...]:
    """Extract quiet_hours keyed by the built target's name.

    Iterating in lockstep with ``targets`` rather than re-deriving the
    webhook index → name mapping keeps the keys aligned with the objects
    the NotificationRouter actually sees.
    """
    pairs: list[tuple[str, QuietHours]] = []
    for wh, target in zip(webhooks, targets, strict=True):
        qh_raw = wh.get("quiet_hours")
        if qh_raw:
            pairs.append((target.name, _build_quiet_hours(qh_raw, target.name)))
    return tuple(pairs)


def _collect_channel_quiet_hours(
    raw: tuple[dict[str, Any], ...],
    targets: tuple[Any, ...],
) -> tuple[tuple[str, QuietHours], ...]:
    """Generic quiet_hours extractor for the new channel kinds (S-163).

    Mirrors :func:`_collect_quiet_hours` but works against any typed
    target tuple whose items expose a ``name`` attribute. Each raw YAML
    dict may carry a ``quiet_hours`` stanza alongside its other fields.
    """
    pairs: list[tuple[str, QuietHours]] = []
    for entry, target in zip(raw, targets, strict=True):
        qh_raw = entry.get("quiet_hours")
        if qh_raw:
            pairs.append((target.name, _build_quiet_hours(qh_raw, target.name)))
    return tuple(pairs)


def _merge_unique_channel_names(
    *named_target_tuples: tuple[Any, ...],
) -> set[str]:
    """Union channel names across every kind and raise on collisions."""
    seen: set[str] = set()
    for tup in named_target_tuples:
        for t in tup:
            if t.name in seen:
                raise ConfigError(
                    f"alerting: duplicate channel name {t.name!r} across target kinds"
                )
            seen.add(t.name)
    return seen


def _build_alerting(data: dict[str, Any]) -> AlertingConfig:
    webhooks = data.get("webhooks", ())
    if isinstance(webhooks, list):
        webhooks = tuple(webhooks)
    raw_overrides = data.get("dedup_window_overrides", {})
    overrides = _parse_dedup_overrides(raw_overrides) if isinstance(raw_overrides, dict) else ()
    webhook_targets = _build_webhook_targets(webhooks)

    email_raw = tuple(data.get("email_targets", ()) or ())
    sms_raw = tuple(data.get("sms_targets", ()) or ())
    telegram_raw = tuple(data.get("telegram_targets", ()) or ())
    whatsapp_raw = tuple(data.get("whatsapp_targets", ()) or ())

    email_targets = _build_email_targets(email_raw)
    sms_targets = _build_sms_targets(sms_raw)
    telegram_targets = _build_telegram_targets(telegram_raw)
    whatsapp_targets = _build_whatsapp_targets(whatsapp_raw)

    known_channels = _merge_unique_channel_names(
        webhook_targets,
        email_targets,
        sms_targets,
        telegram_targets,
        whatsapp_targets,
    )

    routing_rules = _build_routing_rules(data.get("routing_rules", ()), known_channels)
    default_routing = _build_default_routing(
        data.get("default_routing"), known_channels, has_rules=bool(routing_rules)
    )
    otlp_fields = _validate_otlp_settings(data)

    quiet_hours: list[tuple[str, QuietHours]] = list(
        _collect_quiet_hours(webhooks, webhook_targets)
    )
    quiet_hours.extend(_collect_channel_quiet_hours(email_raw, email_targets))
    quiet_hours.extend(_collect_channel_quiet_hours(sms_raw, sms_targets))
    quiet_hours.extend(_collect_channel_quiet_hours(telegram_raw, telegram_targets))
    quiet_hours.extend(_collect_channel_quiet_hours(whatsapp_raw, whatsapp_targets))

    return AlertingConfig(
        dedup_window_seconds=_validate_dedup_window(data),
        dedup_window_overrides=overrides,
        webhooks=webhooks,
        webhook_targets=webhook_targets,
        email_targets=email_targets,
        sms_targets=sms_targets,
        telegram_targets=telegram_targets,
        whatsapp_targets=whatsapp_targets,
        routing_rules=routing_rules,
        default_routing=default_routing,
        quiet_hours_by_channel=tuple(quiet_hours),
        pagerduty_routing_key=_validate_pagerduty_key(data),
        dashboard_url=_validate_dashboard_url_field(data),
        otlp_endpoint=otlp_fields.endpoint,
        otlp_protocol=otlp_fields.protocol,
        otlp_export_interval_seconds=otlp_fields.interval,
        otlp_tls=otlp_fields.tls,
        otlp_tls_ca_file=otlp_fields.tls_ca_file,
        otlp_mtls_cert_file=otlp_fields.mtls_cert_file,
        otlp_mtls_key_file=otlp_fields.mtls_key_file,
    )


_VALID_LLM_BACKENDS: frozenset[str] = frozenset({"", "llama_cpp", "ollama", "cloud"})

# S-099: cloud-backend providers. Empty is legal (graceful absence handled by the
# factory); only ``"anthropic"`` and ``"openai"`` are valid concrete values.
_VALID_CLOUD_PROVIDERS: frozenset[str] = frozenset({"", "anthropic", "openai"})

_LLAMA_CPP_MAX_TOKENS_CAP = 1024  # mirrors LLAMA_CPP_MAX_TOKENS_HARD_CAP


def _build_llm(data: dict[str, Any]) -> LLMConfig:
    """Build and validate the ``llm:`` block (S-070).

    All numeric fields are validated even when ``backend != "llama_cpp"`` —
    a typo'd ``n_ctx`` on an otherwise-disabled config should still surface,
    and future backends may reuse the fields.
    """
    backend = data.get("backend", "")
    if not isinstance(backend, str):
        raise ConfigError(f"llm.backend must be a string, got {type(backend).__name__}")
    if backend not in _VALID_LLM_BACKENDS:
        raise ConfigError(
            "llm.backend must be one of "
            f"{sorted(b for b in _VALID_LLM_BACKENDS if b)}, got {backend!r}"
        )

    model_path = data.get("model_path", "")
    if not isinstance(model_path, str):
        raise ConfigError(f"llm.model_path must be a string, got {type(model_path).__name__}")

    ollama_url = data.get("ollama_url", "http://localhost:11434")
    if not isinstance(ollama_url, str):
        raise ConfigError(f"llm.ollama_url must be a string, got {type(ollama_url).__name__}")

    # S-098: Ollama-specific knobs.
    ollama_model = data.get("ollama_model", "phi4-mini")
    if not isinstance(ollama_model, str):
        raise ConfigError(f"llm.ollama_model must be a string, got {type(ollama_model).__name__}")
    if not 1 <= len(ollama_model) <= 256:
        raise ConfigError(
            f"llm.ollama_model must be a non-empty string of length <= 256, got {ollama_model!r}"
        )

    ollama_timeout_s_raw = data.get("ollama_timeout_s", 30.0)
    if isinstance(ollama_timeout_s_raw, bool) or not isinstance(
        ollama_timeout_s_raw, (int, float)
    ):
        raise ConfigError(
            f"llm.ollama_timeout_s must be a number, got {type(ollama_timeout_s_raw).__name__}"
        )
    ollama_timeout_s = float(ollama_timeout_s_raw)
    if not 1.0 <= ollama_timeout_s <= 600.0:
        raise ConfigError(
            f"llm.ollama_timeout_s must be in [1.0, 600.0], got {ollama_timeout_s_raw!r}"
        )

    n_ctx = data.get("n_ctx", 4096)
    if not isinstance(n_ctx, int) or isinstance(n_ctx, bool):
        raise ConfigError(f"llm.n_ctx must be an integer, got {type(n_ctx).__name__}")
    if not 512 <= n_ctx <= 32768:
        raise ConfigError(f"llm.n_ctx must be in [512, 32768], got {n_ctx!r}")

    n_threads_raw = data.get("n_threads")
    n_threads: int | None
    if n_threads_raw is None:
        n_threads = None
    else:
        if (
            not isinstance(n_threads_raw, int)
            or isinstance(n_threads_raw, bool)
            or n_threads_raw < 1
        ):
            raise ConfigError(
                f"llm.n_threads must be null or an integer >= 1, got {n_threads_raw!r}"
            )
        n_threads = n_threads_raw

    n_gpu_layers = data.get("n_gpu_layers", 0)
    if not isinstance(n_gpu_layers, int) or isinstance(n_gpu_layers, bool) or n_gpu_layers < 0:
        raise ConfigError(f"llm.n_gpu_layers must be an integer >= 0, got {n_gpu_layers!r}")

    max_tokens_default = data.get("max_tokens_default", 256)
    if not isinstance(max_tokens_default, int) or isinstance(max_tokens_default, bool):
        raise ConfigError(
            f"llm.max_tokens_default must be an integer, got {type(max_tokens_default).__name__}"
        )
    if not 1 <= max_tokens_default <= _LLAMA_CPP_MAX_TOKENS_CAP:
        raise ConfigError(
            "llm.max_tokens_default must be in "
            f"[1, {_LLAMA_CPP_MAX_TOKENS_CAP}], got {max_tokens_default!r}"
        )

    temperature_default = data.get("temperature_default", 0.2)
    if isinstance(temperature_default, bool) or not isinstance(temperature_default, (int, float)):
        raise ConfigError(
            f"llm.temperature_default must be a number, got {type(temperature_default).__name__}"
        )
    if not 0.0 <= float(temperature_default) <= 2.0:
        raise ConfigError(
            f"llm.temperature_default must be in [0.0, 2.0], got {temperature_default!r}"
        )

    seed = data.get("seed", 42)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigError(f"llm.seed must be an integer, got {type(seed).__name__}")

    # Alert explanation knobs (S-071).
    explanation_cache_size = data.get("explanation_cache_size", 256)
    if (
        not isinstance(explanation_cache_size, int)
        or isinstance(explanation_cache_size, bool)
        or not 0 <= explanation_cache_size <= 100_000
    ):
        raise ConfigError(
            "llm.explanation_cache_size must be an integer in [0, 100000], "
            f"got {explanation_cache_size!r}"
        )

    explanation_cache_ttl_s = data.get("explanation_cache_ttl_s", 3600)
    if (
        not isinstance(explanation_cache_ttl_s, int)
        or isinstance(explanation_cache_ttl_s, bool)
        or not 1 <= explanation_cache_ttl_s <= 86_400
    ):
        raise ConfigError(
            "llm.explanation_cache_ttl_s must be an integer in [1, 86400], "
            f"got {explanation_cache_ttl_s!r}"
        )

    explanation_max_contributing_events = data.get("explanation_max_contributing_events", 8)
    if (
        not isinstance(explanation_max_contributing_events, int)
        or isinstance(explanation_max_contributing_events, bool)
        or not 1 <= explanation_max_contributing_events <= 64
    ):
        raise ConfigError(
            "llm.explanation_max_contributing_events must be an integer in [1, 64], "
            f"got {explanation_max_contributing_events!r}"
        )

    explanation_max_prompt_chars = data.get("explanation_max_prompt_chars", 8000)
    if (
        not isinstance(explanation_max_prompt_chars, int)
        or isinstance(explanation_max_prompt_chars, bool)
        or not 512 <= explanation_max_prompt_chars <= 32_000
    ):
        raise ConfigError(
            "llm.explanation_max_prompt_chars must be an integer in [512, 32000], "
            f"got {explanation_max_prompt_chars!r}"
        )

    explanation_timeout_s = data.get("explanation_timeout_s", 12.0)
    if isinstance(explanation_timeout_s, bool) or not isinstance(
        explanation_timeout_s, (int, float)
    ):
        raise ConfigError(
            "llm.explanation_timeout_s must be a number, got "
            f"{type(explanation_timeout_s).__name__}"
        )
    explanation_timeout_s = float(explanation_timeout_s)
    if not 1.0 <= explanation_timeout_s <= 120.0:
        raise ConfigError(
            f"llm.explanation_timeout_s must be in [1.0, 120.0], got {explanation_timeout_s!r}"
        )

    # Natural language hunt knobs (S-072). Same validation pattern as explanation knobs.
    hunt_cache_size = data.get("hunt_cache_size", 256)
    if (
        not isinstance(hunt_cache_size, int)
        or isinstance(hunt_cache_size, bool)
        or not 0 <= hunt_cache_size <= 100_000
    ):
        raise ConfigError(
            f"llm.hunt_cache_size must be an integer in [0, 100000], got {hunt_cache_size!r}"
        )

    hunt_cache_ttl_s = data.get("hunt_cache_ttl_s", 3600)
    if (
        not isinstance(hunt_cache_ttl_s, int)
        or isinstance(hunt_cache_ttl_s, bool)
        or not 1 <= hunt_cache_ttl_s <= 86_400
    ):
        raise ConfigError(
            f"llm.hunt_cache_ttl_s must be an integer in [1, 86400], got {hunt_cache_ttl_s!r}"
        )

    hunt_timeout_s = data.get("hunt_timeout_s", 12.0)
    if isinstance(hunt_timeout_s, bool) or not isinstance(hunt_timeout_s, (int, float)):
        raise ConfigError(
            f"llm.hunt_timeout_s must be a number, got {type(hunt_timeout_s).__name__}"
        )
    hunt_timeout_s = float(hunt_timeout_s)
    if not 1.0 <= hunt_timeout_s <= 120.0:
        raise ConfigError(f"llm.hunt_timeout_s must be in [1.0, 120.0], got {hunt_timeout_s!r}")

    hunt_max_results = data.get("hunt_max_results", 100)
    if (
        not isinstance(hunt_max_results, int)
        or isinstance(hunt_max_results, bool)
        or not 1 <= hunt_max_results <= 10_000
    ):
        raise ConfigError(
            f"llm.hunt_max_results must be an integer in [1, 10000], got {hunt_max_results!r}"
        )

    hunt_max_query_chars = data.get("hunt_max_query_chars", 512)
    if (
        not isinstance(hunt_max_query_chars, int)
        or isinstance(hunt_max_query_chars, bool)
        or not 16 <= hunt_max_query_chars <= 16_384
    ):
        raise ConfigError(
            "llm.hunt_max_query_chars must be an integer in [16, 16384], "
            f"got {hunt_max_query_chars!r}"
        )

    # S-099: Cloud backend knobs. Empty values are legal (graceful absence is
    # handled by ``_maybe_load_cloud`` in the factory). The validator only
    # rejects values that could surface a *worse* failure later (typed errors
    # at boot are kinder than typed errors mid-request).
    cloud_provider = data.get("cloud_provider", "")
    if not isinstance(cloud_provider, str):
        raise ConfigError(
            f"llm.cloud_provider must be a string, got {type(cloud_provider).__name__}"
        )
    if cloud_provider not in _VALID_CLOUD_PROVIDERS:
        raise ConfigError(
            "llm.cloud_provider must be one of "
            f"{sorted(p for p in _VALID_CLOUD_PROVIDERS if p)} or empty, "
            f"got {cloud_provider!r}"
        )

    cloud_api_key = data.get("cloud_api_key", "")
    if not isinstance(cloud_api_key, str):
        raise ConfigError(
            f"llm.cloud_api_key must be a string, got {type(cloud_api_key).__name__}"
        )

    cloud_model = data.get("cloud_model", "")
    if not isinstance(cloud_model, str):
        raise ConfigError(f"llm.cloud_model must be a string, got {type(cloud_model).__name__}")
    if len(cloud_model) > 256:
        raise ConfigError(
            f"llm.cloud_model must be a string of length <= 256, got {cloud_model!r}"
        )

    cloud_timeout_s_raw = data.get("cloud_timeout_s", 30.0)
    if isinstance(cloud_timeout_s_raw, bool) or not isinstance(cloud_timeout_s_raw, (int, float)):
        raise ConfigError(
            f"llm.cloud_timeout_s must be a number, got {type(cloud_timeout_s_raw).__name__}"
        )
    cloud_timeout_s = float(cloud_timeout_s_raw)
    if not 1.0 <= cloud_timeout_s <= 600.0:
        raise ConfigError(
            f"llm.cloud_timeout_s must be in [1.0, 600.0], got {cloud_timeout_s_raw!r}"
        )

    cloud_base_url = data.get("cloud_base_url", "")
    if not isinstance(cloud_base_url, str):
        raise ConfigError(
            f"llm.cloud_base_url must be a string, got {type(cloud_base_url).__name__}"
        )

    # S-100: Sigma rule suggestion knobs (FR-066). All defaults preserve
    # current behaviour. Ranges are deliberately wider than the
    # explanation knobs because the drafting workflow is slower and the
    # cached suggestion is reviewed less frequently.
    rule_suggestion_cache_size = data.get("rule_suggestion_cache_size", 64)
    if (
        not isinstance(rule_suggestion_cache_size, int)
        or isinstance(rule_suggestion_cache_size, bool)
        or not 0 <= rule_suggestion_cache_size <= 4096
    ):
        raise ConfigError(
            "llm.rule_suggestion_cache_size must be an integer in [0, 4096], "
            f"got {rule_suggestion_cache_size!r}"
        )

    rule_suggestion_cache_ttl_s = data.get("rule_suggestion_cache_ttl_s", 21_600)
    if (
        not isinstance(rule_suggestion_cache_ttl_s, int)
        or isinstance(rule_suggestion_cache_ttl_s, bool)
        or not 1 <= rule_suggestion_cache_ttl_s <= 86_400
    ):
        raise ConfigError(
            "llm.rule_suggestion_cache_ttl_s must be an integer in [1, 86400], "
            f"got {rule_suggestion_cache_ttl_s!r}"
        )

    rule_suggestion_min_tp = data.get("rule_suggestion_min_tp", 3)
    if (
        not isinstance(rule_suggestion_min_tp, int)
        or isinstance(rule_suggestion_min_tp, bool)
        or not 1 <= rule_suggestion_min_tp <= 100
    ):
        raise ConfigError(
            "llm.rule_suggestion_min_tp must be an integer in [1, 100], "
            f"got {rule_suggestion_min_tp!r}"
        )

    rule_suggestion_window_days = data.get("rule_suggestion_window_days", 0)
    if (
        not isinstance(rule_suggestion_window_days, int)
        or isinstance(rule_suggestion_window_days, bool)
        or not 0 <= rule_suggestion_window_days <= 365
    ):
        raise ConfigError(
            "llm.rule_suggestion_window_days must be an integer in [0, 365], "
            f"got {rule_suggestion_window_days!r}"
        )

    rule_suggestion_timeout_raw = data.get("rule_suggestion_timeout_s", 30.0)
    if isinstance(rule_suggestion_timeout_raw, bool) or not isinstance(
        rule_suggestion_timeout_raw, (int, float)
    ):
        raise ConfigError(
            "llm.rule_suggestion_timeout_s must be a number, "
            f"got {type(rule_suggestion_timeout_raw).__name__}"
        )
    rule_suggestion_timeout_s = float(rule_suggestion_timeout_raw)
    if not 1.0 <= rule_suggestion_timeout_s <= 120.0:
        raise ConfigError(
            "llm.rule_suggestion_timeout_s must be in [1.0, 120.0], "
            f"got {rule_suggestion_timeout_raw!r}"
        )

    return LLMConfig(
        backend=backend,
        model_path=model_path,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_timeout_s=ollama_timeout_s,
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        max_tokens_default=max_tokens_default,
        temperature_default=float(temperature_default),
        seed=seed,
        explanation_cache_size=explanation_cache_size,
        explanation_cache_ttl_s=explanation_cache_ttl_s,
        explanation_max_contributing_events=explanation_max_contributing_events,
        explanation_max_prompt_chars=explanation_max_prompt_chars,
        explanation_timeout_s=explanation_timeout_s,
        hunt_cache_size=hunt_cache_size,
        hunt_cache_ttl_s=hunt_cache_ttl_s,
        hunt_timeout_s=hunt_timeout_s,
        hunt_max_results=hunt_max_results,
        hunt_max_query_chars=hunt_max_query_chars,
        cloud_provider=cloud_provider,
        cloud_api_key=cloud_api_key,
        cloud_model=cloud_model,
        cloud_timeout_s=cloud_timeout_s,
        cloud_base_url=cloud_base_url,
        rule_suggestion_cache_size=rule_suggestion_cache_size,
        rule_suggestion_cache_ttl_s=rule_suggestion_cache_ttl_s,
        rule_suggestion_min_tp=rule_suggestion_min_tp,
        rule_suggestion_window_days=rule_suggestion_window_days,
        rule_suggestion_timeout_s=rule_suggestion_timeout_s,
    )


def _require_bool(data: dict[str, Any], key: str, default: bool, label: str) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be a boolean, got {type(value).__name__}")
    return value


def _require_pos_int(data: dict[str, Any], key: str, default: int, label: str) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{label} must be an integer >= 1, got {value!r}")
    return value


def _require_number(data: dict[str, Any], key: str, default: float, label: str) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number, got {type(value).__name__}")
    return float(value)


def _build_sub_score_weights(data: dict[str, Any]) -> UEBASubScoreWeights:
    """Build and validate the ``ueba.sub_score_weights`` block."""
    defaults = UEBASubScoreWeights()
    weights = UEBASubScoreWeights(
        time_of_day=_require_number(
            data, "time_of_day", defaults.time_of_day, "ueba.sub_score_weights.time_of_day"
        ),
        source_novelty=_require_number(
            data,
            "source_novelty",
            defaults.source_novelty,
            "ueba.sub_score_weights.source_novelty",
        ),
        volume=_require_number(data, "volume", defaults.volume, "ueba.sub_score_weights.volume"),
        pattern_novelty=_require_number(
            data,
            "pattern_novelty",
            defaults.pattern_novelty,
            "ueba.sub_score_weights.pattern_novelty",
        ),
    )
    for name, val in (
        ("time_of_day", weights.time_of_day),
        ("source_novelty", weights.source_novelty),
        ("volume", weights.volume),
        ("pattern_novelty", weights.pattern_novelty),
    ):
        if not (0.0 < val <= 1.0):
            raise ConfigError(f"ueba.sub_score_weights.{name} must be in (0.0, 1.0], got {val!r}")
    total = weights.time_of_day + weights.source_novelty + weights.volume + weights.pattern_novelty
    if abs(total - 1.0) > 1e-6:
        raise ConfigError(f"ueba.sub_score_weights must sum to 1.0 (got {total})")
    return weights


def _build_ueba(data: dict[str, Any]) -> UEBAConfig:
    """Build UEBAConfig from a YAML ``ueba:`` section.

    All fields are optional — omitted keys fall back to UEBAConfig defaults.
    Type mismatches raise ConfigError with the offending key labelled.
    """
    defaults = UEBAConfig()
    ema_alpha = _require_number(data, "ema_alpha", defaults.ema_alpha, "ueba.ema_alpha")
    if not (0.0 < ema_alpha <= 1.0):
        raise ConfigError(f"ueba.ema_alpha must be in (0, 1], got {ema_alpha!r}")

    score_threshold = _require_number(
        data, "score_threshold", defaults.score_threshold, "ueba.score_threshold"
    )
    if not (0.0 <= score_threshold <= 1.0):
        raise ConfigError(f"ueba.score_threshold must be in [0.0, 1.0], got {score_threshold!r}")

    weights_raw = data.get("sub_score_weights", {})
    if not isinstance(weights_raw, dict):
        raise ConfigError("ueba.sub_score_weights must be a mapping")
    sub_score_weights = _build_sub_score_weights(weights_raw)

    alert_cooldown_seconds = _require_pos_int(
        data,
        "alert_cooldown_seconds",
        defaults.alert_cooldown_seconds,
        "ueba.alert_cooldown_seconds",
    )

    return UEBAConfig(
        enabled=_require_bool(data, "enabled", defaults.enabled, "ueba.enabled"),
        warmup_days=_require_pos_int(
            data, "warmup_days", defaults.warmup_days, "ueba.warmup_days"
        ),
        warmup_min_events=_require_pos_int(
            data,
            "warmup_min_events",
            defaults.warmup_min_events,
            "ueba.warmup_min_events",
        ),
        max_entities=_require_pos_int(
            data, "max_entities", defaults.max_entities, "ueba.max_entities"
        ),
        ema_alpha=ema_alpha,
        source_ip_cap=_require_pos_int(
            data, "source_ip_cap", defaults.source_ip_cap, "ueba.source_ip_cap"
        ),
        template_top_k=_require_pos_int(
            data, "template_top_k", defaults.template_top_k, "ueba.template_top_k"
        ),
        score_threshold=score_threshold,
        sub_score_weights=sub_score_weights,
        alert_cooldown_seconds=alert_cooldown_seconds,
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


# PEP 562 lazy re-export of `build_seerflow_config` — breaks the cycle (S-226).
def __getattr__(name: str) -> Any:
    if name == "build_seerflow_config":
        from seerflow._threat_intel_builders import build_seerflow_config

        return build_seerflow_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
