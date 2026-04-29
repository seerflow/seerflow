"""Top-level lifecycle manager for all TAXII feed consumers."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import aiohttp

from seerflow.threat_intel.circuit import AuthCircuitBreaker
from seerflow.threat_intel.client import TAXIIClient
from seerflow.threat_intel.consumer import TAXIIFeedConsumer
from seerflow.threat_intel.metrics import TAXIIMetricsRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from seerflow.config import (
        TAXIIAuthConfig,
        TAXIIFeedConfig,
        ThreatIntelConfig,
    )
    from seerflow.storage.protocols import ModelStore

_log = logging.getLogger("seerflow")


class TAXIIFeedManager:
    """Owns the aiohttp session and all enabled feed consumers."""

    def __init__(
        self,
        *,
        config: ThreatIntelConfig,
        model_store: ModelStore,
    ) -> None:
        self._cfg = config
        self._store = model_store
        self._session: aiohttp.ClientSession | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop = asyncio.Event()
        self._metrics = TAXIIMetricsRegistry()
        self._snapshot_listeners: list[Callable[[str], None]] = []

    @property
    def metrics(self) -> TAXIIMetricsRegistry:
        return self._metrics

    def feed_ids(self) -> tuple[str, ...]:
        return tuple(self._tasks.keys())

    async def start(self) -> list[str]:
        if not self._cfg.enabled:
            return []
        if self._session is not None:
            raise RuntimeError(
                "TAXIIFeedManager.start() called while already running; "
                "call stop() before re-starting"
            )
        # Fresh stop event — clears any prior set() from a previous stop()
        # so a restart cycle does not leave run_forever() permanently
        # short-circuited.
        self._stop = asyncio.Event()
        # AC1 (S-227): pin each enabled feed's hostname to the IP captured
        # at startup so per-request DNS cannot drift to a private/IMDS
        # address at runtime. Feeds with allow_private_addresses=True are
        # excluded — they fall through to aiohttp's default resolver.
        # Deferred import: ``seerflow.threat_intel.dns`` imports
        # ``_resolve_feed_with_private_ip_guard`` from
        # ``seerflow._config_validation``, which itself imports from
        # ``seerflow.config``. Importing ``dns`` at this module's top
        # would re-enter the same ``seerflow.config`` ↔ builder chain
        # that ``_threat_intel_builders`` already side-steps.
        from seerflow.threat_intel.dns import StaticResolver, build_static_resolver_map

        resolver_map = build_static_resolver_map(self._cfg)
        if resolver_map:
            connector = aiohttp.TCPConnector(resolver=StaticResolver(resolver_map))
            self._session = aiohttp.ClientSession(connector=connector)
        else:
            self._session = aiohttp.ClientSession()
        failed: list[str] = []
        for feed_cfg in self._cfg.feeds:
            if not feed_cfg.enabled:
                continue
            try:
                consumer = self._build_consumer(feed_cfg)
            except RuntimeError as exc:
                _log.error("taxii: failed to construct feed=%s: %s", feed_cfg.id, exc)
                failed.append(feed_cfg.id)
                continue
            self._tasks[feed_cfg.id] = asyncio.create_task(
                consumer.run_forever(self._stop), name=f"taxii-feed-{feed_cfg.id}"
            )
        return failed

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.wait(
                self._tasks.values(),
                timeout=2.0,
                return_when=asyncio.ALL_COMPLETED,
            )
            pending = [t for t in self._tasks.values() if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _build_consumer(self, feed_cfg: TAXIIFeedConfig) -> TAXIIFeedConsumer:
        if self._session is None:
            # Production guard, not an assert — assert is stripped under -O.
            raise RuntimeError("_build_consumer called before start(); session is not initialised")
        auth_header, basic = _resolve_auth(feed_cfg.auth)
        client = TAXIIClient(
            session=self._session,
            auth_header=auth_header,
            basic_auth=basic,
            timeout_s=self._cfg.request_timeout_s,
        )
        return TAXIIFeedConsumer(
            feed_config=feed_cfg,
            defaults=self._cfg,
            model_store=self._store,
            client=client,
            metrics=self._metrics,
            breaker=AuthCircuitBreaker(),
            on_persist=self._fire_snapshot_listeners,
        )

    def register_snapshot_listener(self, callback: Callable[[str], None]) -> None:
        """Register a sync callback fired after each successful snapshot persist."""
        self._snapshot_listeners.append(callback)

    def _fire_snapshot_listeners(self, feed_id: str) -> None:
        """Invoke all registered listeners; isolate exceptions per listener."""
        for cb in self._snapshot_listeners:
            try:
                cb(feed_id)
            except Exception:
                _log.exception(
                    "taxii: snapshot listener raised for feed=%s; continuing",
                    feed_id,
                )


def _resolve_auth(
    auth: TAXIIAuthConfig | None,
) -> tuple[dict[str, str] | None, aiohttp.BasicAuth | None]:
    if auth is None:
        return None, None
    match auth.kind:
        case "api_key":
            if not auth.api_key_env:
                raise RuntimeError("api_key auth requires api_key_env")
            token = os.environ.get(auth.api_key_env)
            if not token:
                raise RuntimeError(f"env var {auth.api_key_env} is unset")
            prefix = "Bearer " if auth.api_key_header.lower() == "authorization" else ""
            return {auth.api_key_header: f"{prefix}{token}"}, None
        case "basic":
            if not auth.username_env or not auth.password_env:
                raise RuntimeError("basic auth requires username_env and password_env")
            u = os.environ.get(auth.username_env)
            p = os.environ.get(auth.password_env)
            if not u or not p:
                raise RuntimeError(f"env vars {auth.username_env}/{auth.password_env} unset")
            return None, aiohttp.BasicAuth(login=u, password=p)
        case _:
            raise RuntimeError(f"unknown auth kind: {auth.kind}")
