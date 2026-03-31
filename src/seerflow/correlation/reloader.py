"""Hot-reload watcher for correlation and Sigma rule directories."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import watchfiles

from seerflow.correlation.engine import CorrelationEngine
from seerflow.correlation.rule_loader import load_correlation_rules

if TYPE_CHECKING:
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.window import EntityWindowBuffer

_log = logging.getLogger("seerflow")


class _YamlFilter(watchfiles.DefaultFilter):
    """Only trigger on .yml and .yaml file changes."""

    allowed_extensions = (".yml", ".yaml")

    def __call__(self, change: watchfiles.Change, path: str) -> bool:
        return super().__call__(change, path) and path.endswith(self.allowed_extensions)


class RuleReloader:
    """Watches rule directories and hot-reloads engines on YAML changes."""

    __slots__ = (
        "_correlation_dirs",
        "_correlation_holder",
        "_sigma_dirs",
        "_sigma_holder",
        "_window_buffer",
    )

    def __init__(
        self,
        *,
        correlation_holder: EngineHolder[CorrelationEngine | None] | None = None,
        correlation_dirs: list[str] | None = None,
        window_buffer: EntityWindowBuffer | None = None,
        sigma_holder: EngineHolder[Any] | None = None,
        sigma_dirs: list[str] | None = None,
    ) -> None:
        self._correlation_holder = correlation_holder
        self._correlation_dirs = correlation_dirs or []
        self._window_buffer = window_buffer
        self._sigma_holder = sigma_holder
        self._sigma_dirs = sigma_dirs or []

    async def watch(self) -> None:
        """Watch rule directories for changes and reload engines.

        Performs an initial load of all existing rules, then enters the
        watch loop.  Returns immediately if no directories to watch.
        """
        watch_dirs = [*self._correlation_dirs, *self._sigma_dirs]
        if not watch_dirs:
            return

        # Initial load so existing rules are picked up on startup
        if self._correlation_dirs and self._correlation_holder is not None:
            self._reload_correlation()
        if self._sigma_dirs and self._sigma_holder is not None:
            self._reload_sigma()

        async for _changes in watchfiles.awatch(
            *watch_dirs,
            watch_filter=_YamlFilter(),
            debounce=1000,
        ):
            if self._correlation_dirs and self._correlation_holder is not None:
                self._reload_correlation()
            if self._sigma_dirs and self._sigma_holder is not None:
                self._reload_sigma()

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
            _log.info(
                "Reloaded correlation engine with %d rules",
                len(rules),
            )
        except Exception:
            _log.warning(
                "Failed to reload correlation rules; keeping existing engine",
                exc_info=True,
            )

    def _reload_sigma(self) -> None:
        """Reload Sigma rules from disk and replace the engine.

        Sigma engine reload is not yet implemented — placeholder for
        future integration.
        """
        _log.info("Sigma rule reload triggered (not yet implemented)")
