"""Main pipeline orchestrator connecting all components."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from seerflow.receivers.manager import ReceiverManager

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from seerflow.config import SeerflowConfig
    from seerflow.receivers.base import RawEvent

_log = logging.getLogger(__name__)


class Pipeline:
    """Ingestion pipeline — manages receivers and consumer loop."""

    __slots__ = ("_config", "_manager", "_running")

    def __init__(self, manager: ReceiverManager, config: SeerflowConfig) -> None:
        self._manager = manager
        self._config = config
        self._running = False

    @property
    def manager(self) -> ReceiverManager:
        return self._manager

    @property
    def config(self) -> SeerflowConfig:
        return self._config

    async def run(self, handler: Callable[[RawEvent], Awaitable[None]]) -> None:
        """Consumer loop — processes events until shutdown."""
        self._running = True
        while self._running:
            event = await self._manager.get_event()
            if event is None:
                break
            try:
                await handler(event)
            except Exception:
                _log.exception("Handler error processing event from %s", event.source_type)
        self._running = False

    async def stop(self) -> None:
        """Stop the pipeline and all receivers."""
        self._running = False
        await self._manager.stop()


async def build_pipeline(config: SeerflowConfig) -> Pipeline:
    """Build and start the ingestion pipeline from config."""
    r = config.receivers
    mgr = ReceiverManager(queue_maxsize=r.queue_maxsize)

    if r.syslog_enabled:
        from seerflow.receivers.syslog import SyslogReceiver

        mgr.register(
            "syslog",
            SyslogReceiver(
                mgr,
                source_id="syslog",
                udp_port=r.syslog_udp_port,
                tcp_port=r.syslog_tcp_port,
                bind_addr=r.bind_addr,
                tcp_enabled=r.syslog_tcp_enabled,
            ),
        )

    if r.otlp_grpc_enabled:
        from seerflow.receivers.otlp_grpc import OtlpGrpcReceiver

        mgr.register(
            "otlp-grpc",
            OtlpGrpcReceiver(
                mgr,
                source_id="otlp-grpc",
                bind_addr=r.bind_addr,
                port=r.otlp_grpc_port,
            ),
        )

    if r.otlp_http_enabled:
        from seerflow.receivers.otlp_http import OtlpHttpReceiver

        mgr.register(
            "otlp-http",
            OtlpHttpReceiver(
                mgr,
                source_id="otlp-http",
                bind_addr=r.bind_addr,
                port=r.otlp_http_port,
            ),
        )

    if r.webhooks:
        from seerflow.receivers.webhook import WebhookConfig, WebhookReceiver

        wh_configs = tuple(
            WebhookConfig(
                path=w.path,
                auth_header=w.auth_header,
                auth_token=w.auth_token,
                field_mapping=w.field_mapping,
                source_id=w.source_id,
            )
            for w in r.webhooks
        )
        mgr.register(
            "webhook",
            WebhookReceiver(
                mgr,
                configs=wh_configs,
                bind_addr=r.bind_addr,
                port=r.webhook_port,
            ),
        )

    if r.file_paths:
        from seerflow.receivers.file_tail import FileTailReceiver

        mgr.register(
            "file",
            FileTailReceiver(
                mgr,
                source_id="file",
                file_paths=r.file_paths,
                checkpoint_dir=r.file_checkpoint_dir,
                debounce_ms=r.file_debounce_ms,
                allowed_log_roots=r.allowed_log_roots,
            ),
        )

    if r.stdin_enabled:
        from seerflow.receivers.stdin import StdinReceiver

        mgr.register(
            "stdin",
            StdinReceiver(mgr, source_id="stdin"),
        )

    failed = await mgr.start()
    if failed:
        started = [k for k in mgr._receivers if k not in failed]
        if not started:
            await mgr.stop()
            msg = f"All receivers failed to start: {failed}"
            raise RuntimeError(msg)
        _log.warning(
            "Some receivers failed to start: %s (continuing with: %s)",
            failed,
            started,
        )

    return Pipeline(mgr, config)
