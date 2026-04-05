"""Hot-reload watcher for correlation rule directories.

Uses ``watchfiles.awatch()`` (Rust inotify) to detect YAML file changes
and atomically rebuild the correlation engine without restarting the pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import watchfiles

from seerflow.correlation.engine import CorrelationEngine
from seerflow.correlation.rule_loader import load_correlation_rules

if TYPE_CHECKING:
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.window import EntityWindowBuffer

_log = logging.getLogger("seerflow")


class _YamlFilter(watchfiles.DefaultFilter):
    """Only trigger on .yml and .yaml file changes."""

    allowed_extensions: tuple[str, ...] = (".yml", ".yaml")

    def __call__(self, change: watchfiles.Change, path: str) -> bool:
        return super().__call__(change, path) and path.endswith(self.allowed_extensions)


class RuleReloader:
    """Watches rule directories and hot-reloads the correlation engine on YAML changes."""

    __slots__ = ("_correlation_dirs", "_correlation_holder", "_window_buffer")

    def __init__(
        self,
        *,
        correlation_holder: EngineHolder[CorrelationEngine | None] | None = None,
        correlation_dirs: list[str] | None = None,
        window_buffer: EntityWindowBuffer | None = None,
    ) -> None:
        self._correlation_holder = correlation_holder
        self._correlation_dirs = correlation_dirs or []
        self._window_buffer = window_buffer

    async def watch(self) -> None:
        """Watch rule directories for changes and reload the engine.

        Performs an initial load of all existing rules, then enters the
        watch loop. Returns immediately if no directories to watch.
        """
        if not self._correlation_dirs:
            return

        if self._correlation_holder is not None:
            await asyncio.to_thread(self._reload_correlation)

        async for _changes in watchfiles.awatch(
            *self._correlation_dirs,
            watch_filter=_YamlFilter(),
            debounce=1600,
        ):
            if self._correlation_holder is not None:
                await asyncio.to_thread(self._reload_correlation)

    def _reload_correlation(self) -> None:
        """Reload correlation rules from disk and replace the engine."""
        try:
            rules = load_correlation_rules(self._correlation_dirs)
            if self._window_buffer is None:
                _log.warning("Cannot reload correlation engine: no window buffer")
                return
            new_engine = CorrelationEngine(rules=rules, window=self._window_buffer)
            if self._correlation_holder is not None:
                self._correlation_holder.engine = new_engine
            if len(rules) == 0:
                _log.warning("Correlation engine reloaded with 0 rules — all detection disabled")
            else:
                _log.info("Reloaded correlation engine with %d rules", len(rules))
        except Exception:
            _log.warning(
                "Failed to reload correlation rules; keeping existing engine",
                exc_info=True,
            )
