"""Tail-mode config builder for ``seerflow tail``."""

from __future__ import annotations

from seerflow.config import ReceiverConfig, SeerflowConfig, load_config


def _build_tail_config(paths: list[str], config_path: str | None = None) -> SeerflowConfig:
    """Build a SeerflowConfig for tail mode (file receivers only)."""
    base = load_config(config_path)
    tail_receivers = ReceiverConfig(
        syslog_enabled=False,
        otlp_grpc_enabled=False,
        otlp_http_enabled=False,
        webhook_enabled=False,
        file_paths=tuple(paths),
    )
    return SeerflowConfig(
        receivers=tail_receivers,
        storage=base.storage,
        detection=base.detection,
        alerting=base.alerting,
        llm=base.llm,
        log_level=base.log_level,
    )
