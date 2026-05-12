"""``NaturalLanguageHuntService`` — orchestrator for S-072.

Translates a natural language threat-hunt query into a structured
``EventQuery`` via the configured ``LLMBackend``, executes the query
against the ``LogStore``, and returns a ``HuntResult``.

The orchestrator owns the only I/O in this subpackage:

- LLM call (wrapped in ``asyncio.wait_for`` with the configured timeout)
- Storage query
- Cache read/write

Pure helpers (prompt builder, parser, validator) are imported and called
in this single coordinator function.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from seerflow.llm.hunt._to_event_query import translate_to_event_query
from seerflow.llm.hunt.parser import parse_response
from seerflow.llm.hunt.prompt import build_prompt
from seerflow.llm.hunt.result import HuntResult

if TYPE_CHECKING:
    from seerflow.config import LLMConfig
    from seerflow.llm.hunt.cache import HuntCache
    from seerflow.llm.protocol import LLMBackend
    from seerflow.storage.protocols import LogStore

_log = logging.getLogger(__name__)

# Default time window applied when the LLM does not produce one. 24 hours
# is the same window used by the explanation service's event lookback.
_DEFAULT_WINDOW_NS = 24 * 3_600 * 1_000_000_000


class NaturalLanguageHuntService:
    """Translate NL hunt queries to ``EventQuery`` + execute them."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        cache: HuntCache,
        cfg: LLMConfig,
        log_store: LogStore,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.cfg = cfg
        self.log_store = log_store

    async def hunt(self, nl_query: str) -> HuntResult:
        """Translate ``nl_query`` and return matching events.

        Raises:
            ValueError: if ``nl_query`` is empty/whitespace-only or longer
                than ``cfg.hunt_max_query_chars``.
            asyncio.TimeoutError: if the LLM backend exceeds
                ``cfg.hunt_timeout_s``.

        Any other backend exception is propagated to the caller (the API
        route translates it to HTTP 502; the CLI prints and returns
        non-zero).
        """
        stripped = nl_query.strip()
        if not stripped:
            raise ValueError("nl_query must be non-empty")
        if len(stripped) > self.cfg.hunt_max_query_chars:
            raise ValueError(
                f"nl_query is too long ({len(stripped)} > {self.cfg.hunt_max_query_chars})"
            )

        cached_filters = await self.cache.get(stripped)
        latency_ms = 0.0
        if cached_filters is not None:
            filters = cached_filters
            cached = True
            _log.debug("hunt: cache hit query=%r", stripped[:80])
        else:
            prompt = build_prompt(stripped, max_query_chars=self.cfg.hunt_max_query_chars)
            t0 = time.monotonic()
            try:
                text = await asyncio.wait_for(
                    self.backend.complete(
                        prompt,
                        max_tokens=self.cfg.max_tokens_default,
                        temperature=self.cfg.temperature_default,
                    ),
                    timeout=self.cfg.hunt_timeout_s,
                )
            except TimeoutError:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                _log.warning(
                    "hunt: backend timeout query=%r elapsed_ms=%.1f",
                    stripped[:80],
                    elapsed_ms,
                )
                raise
            latency_ms = (time.monotonic() - t0) * 1000.0
            filters = parse_response(text, original_query=stripped)
            await self.cache.put(stripped, filters)
            cached = False
            _log.info("hunt: translated query=%r filters=%s", stripped[:80], filters)

        query = translate_to_event_query(
            filters,
            default_window_ns=_DEFAULT_WINDOW_NS,
            default_limit=self.cfg.hunt_max_results,
            now_ns=time.time_ns(),
        )
        page = await self.log_store.query_events(query)
        events = tuple(page.items)
        truncated = page.total > len(events)

        return HuntResult(
            query=nl_query,
            filters=dict(filters),
            events=events,
            total=page.total,
            model=self.backend.name,
            generated_at_ns=time.time_ns(),
            latency_ms=latency_ms,
            cached=cached,
            truncated=truncated,
        )
