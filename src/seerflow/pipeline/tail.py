"""Tail-mode config builder for ``seerflow tail``."""

from __future__ import annotations

import dataclasses

from seerflow.config import ReceiverConfig, SeerflowConfig, load_config


def _build_tail_config(paths: list[str], config_path: str | None = None) -> SeerflowConfig:
    """Build a SeerflowConfig for tail mode (file receivers only).

    S-312/FR-071: ``seerflow tail`` enables the console sink on stdout by
    default so a headless operator sees alerts with zero config. An explicit
    ``console_enabled: false`` in the loaded config is overridden here because
    silent ``tail`` is the exact gap FR-071 closes; operators who want a
    quieter feed can raise ``console_min_severity`` in their config.
    """
    base = load_config(config_path)
    tail_receivers = ReceiverConfig(
        syslog_enabled=False,
        otlp_grpc_enabled=False,
        otlp_http_enabled=False,
        webhook_enabled=False,
        file_paths=tuple(paths),
    )
    tail_alerting = dataclasses.replace(
        base.alerting,
        console_enabled=True,
        console_stream="stdout",
    )
    return SeerflowConfig(
        receivers=tail_receivers,
        storage=base.storage,
        detection=base.detection,
        alerting=tail_alerting,
        llm=base.llm,
        log_level=base.log_level,
    )
