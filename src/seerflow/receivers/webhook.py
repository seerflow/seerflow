"""Webhooks receiver -- generic HTTP POST ingestion with field mapping."""

from __future__ import annotations

import hmac
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiohttp.web

from seerflow.receivers.base import RawEvent

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from seerflow.receivers.manager import ReceiverManager

_log = logging.getLogger(__name__)
_MAX_REQUEST_BYTES = 4 * 1024 * 1024  # 4 MB


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    """Configuration for a single webhook endpoint.

    Auth uses bearer-token comparison via constant-time ``hmac.compare_digest``.
    Both ``auth_header`` and ``auth_token`` must be set together or both empty.
    """

    path: str = "/ingest/webhook"
    auth_header: str = ""
    auth_token: str = ""
    field_mapping: dict[str, str] = field(default_factory=dict)
    source_id: str = "webhook"

    def __post_init__(self) -> None:
        if bool(self.auth_header) != bool(self.auth_token):
            msg = "auth_header and auth_token must both be set or both be empty"
            raise ValueError(msg)


def _extract_field(data: dict[str, Any], dot_path: str) -> str | None:
    """Extract a scalar value from nested dict using dot-path (e.g. 'body.text').

    Returns None if the path is missing or the terminal value is not a scalar.
    """
    keys = dot_path.split(".")
    current: Any = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    if not isinstance(current, (str, int, float, bool)):
        return None
    return str(current)


class WebhookReceiver:
    """Generic webhook HTTP POST receiver with field mapping and auth.

    NOT thread-safe for start/stop -- single event-loop only.
    Use ``port=0`` in tests to let the OS assign an ephemeral port.
    Read the actual port via the ``actual_port`` property after ``start()``.
    """

    __slots__ = (
        "_actual_port",
        "_bind_addr",
        "_configs",
        "_manager",
        "_port",
        "_runner",
        "_started",
        "_stopped",
    )

    def __init__(
        self,
        manager: ReceiverManager,
        *,
        configs: tuple[WebhookConfig, ...] = (WebhookConfig(),),
        bind_addr: str = "0.0.0.0",  # noqa: S104  # nosec B104
        port: int = 8081,
    ) -> None:
        if not bind_addr:
            msg = "bind_addr must be a non-empty string"
            raise ValueError(msg)
        self._manager = manager
        self._configs = configs
        self._bind_addr = bind_addr
        self._port = port
        self._runner: aiohttp.web.AppRunner | None = None
        self._actual_port: int = port
        self._started = False
        self._stopped = False

    async def start(self) -> None:
        """Start the HTTP server on the configured address and port."""
        if self._started:
            return
        app = aiohttp.web.Application(client_max_size=_MAX_REQUEST_BYTES)
        for config in self._configs:
            app.router.add_post(config.path, self._make_handler(config))
        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((self._bind_addr, self._port))
            self._actual_port = sock.getsockname()[1]
            site = aiohttp.web.SockSite(runner, sock)
            await site.start()
        except Exception:
            sock.close()
            await runner.cleanup()
            raise
        self._runner = runner
        self._started = True
        _log.info(
            "Webhook receiver listening on %s:%d",
            self._bind_addr,
            self._actual_port,
        )

    async def stop(self) -> None:
        """Gracefully stop the HTTP server."""
        if self._stopped:
            return
        self._stopped = True
        if self._runner is not None:
            await self._runner.cleanup()
            _log.info("Webhook receiver stopped")

    def is_healthy(self) -> bool:
        """Return True if the receiver has started and not been stopped."""
        return self._started and not self._stopped

    @property
    def actual_port(self) -> int:
        """Actual bound port (useful when configured with port=0)."""
        return self._actual_port

    def _make_handler(
        self,
        config: WebhookConfig,
    ) -> Callable[
        [aiohttp.web.Request],
        Coroutine[Any, Any, aiohttp.web.Response],
    ]:
        """Create a request handler bound to a specific WebhookConfig."""

        async def handler(
            request: aiohttp.web.Request,
        ) -> aiohttp.web.Response:
            # Auth check (bearer-token, constant-time comparison)
            if config.auth_header:
                provided = request.headers.get(config.auth_header, "")
                if not hmac.compare_digest(provided, config.auth_token):
                    return aiohttp.web.Response(status=401, text="Unauthorized")

            # Content-type uses aiohttp's parsed media type (strips charset params)
            content_type = request.content_type
            try:
                if content_type == "application/json":
                    data: dict[str, Any] = await request.json()
                elif content_type == "application/x-www-form-urlencoded":
                    post_data = await request.post()
                    data = dict(post_data)
                else:
                    return aiohttp.web.Response(status=415, text="Unsupported content type")
            except json.JSONDecodeError as exc:
                _log.debug("Malformed webhook body: %s", exc)
                return aiohttp.web.Response(status=400, text="Malformed request body")

            # Apply field mapping to metadata (scalars only)
            metadata: dict[str, Any] = {}
            for target_field, source_path in config.field_mapping.items():
                value = _extract_field(data, source_path) if isinstance(data, dict) else None
                if value is not None:
                    metadata[target_field] = value

            body_bytes = json.dumps(data).encode("utf-8") if isinstance(data, dict) else b"{}"
            event = RawEvent(
                data=body_bytes,
                source_type="webhook",
                source_id=config.source_id,
                received_ns=time.time_ns(),
                metadata=metadata,
            )
            if not await self._manager.put_event(event):
                return aiohttp.web.Response(status=429, text="Queue full")
            return aiohttp.web.Response(status=200, text="OK")

        return handler
