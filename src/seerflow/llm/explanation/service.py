"""``AlertExplanationService`` — orchestrator for S-071.

Loads alert + contributing events + entity baseline, builds the prompt,
calls the LLM backend with a wall-clock timeout, parses the response,
and caches the result.

Pure I/O happens here; the prompt builder and parser are kept pure so
this is the only file in ``llm/explanation/`` that touches storage or
asyncio primitives beyond the cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from seerflow.llm.explanation.context import load_entity_baseline_context
from seerflow.llm.explanation.parser import parse_response
from seerflow.llm.explanation.prompt import build_prompt
from seerflow.llm.explanation.result import ExplanationResult
from seerflow.models.query import EventQuery, TimeRange

if TYPE_CHECKING:
    import uuid

    from seerflow.config import LLMConfig
    from seerflow.llm.explanation.cache import ExplanationCache
    from seerflow.llm.protocol import LLMBackend
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.protocols import AlertStore, LogStore
    from seerflow.ueba.store import BaselineStore

_log = logging.getLogger(__name__)

# Time window (nanoseconds) opened around the alert when querying for
# contributing events. Wide enough to find recent events even when
# clocks drift modestly; narrow enough to keep the query cheap.
_EVENT_LOOKBACK_NS = 24 * 3600 * 1_000_000_000  # 24 hours


def _filter_events_by_ids(
    events: tuple[SeerflowEvent, ...],
    wanted_ids: tuple[uuid.UUID, ...],
    cap: int,
) -> tuple[tuple[SeerflowEvent, ...], bool]:
    """Pick events whose ``event_id`` is in ``wanted_ids`` (cap at ``cap``).

    Returns ``(picked, truncated)``. ``truncated`` is ``True`` when the
    picked count differs from ``len(wanted_ids)`` (stale event IDs) OR
    when the cap dropped events the alert referenced.
    """
    wanted_set = set(wanted_ids)
    picked = tuple(e for e in events if e.event_id in wanted_set)
    truncated_due_to_missing = len(picked) != len(wanted_ids)
    if len(picked) > cap:
        picked = picked[-cap:]  # keep newest by position in the returned page
        return picked, True
    return picked, truncated_due_to_missing


class AlertExplanationService:
    """Generate (and cache) human-readable alert explanations on demand."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        cache: ExplanationCache,
        cfg: LLMConfig,
        alert_store: AlertStore,
        log_store: LogStore,
        baseline_store: BaselineStore | None,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.cfg = cfg
        self.alert_store = alert_store
        self.log_store = log_store
        self.baseline_store = baseline_store

    async def explain(self, alert_id: str) -> ExplanationResult | None:
        """Return an explanation for ``alert_id`` (cached when available).

        Returns ``None`` when the alert is unknown. Re-raises any backend
        exception (including ``asyncio.TimeoutError`` from the wall-clock
        guard) — the route translates these to HTTP 502.
        """
        cached = await self.cache.get(alert_id)
        if cached is not None:
            _log.info("explanation: cache hit alert_id=%s", alert_id)
            return cached

        alert = await self.alert_store.get_alert_by_id(alert_id)
        if alert is None:
            return None

        time_range = TimeRange(
            start_ns=max(0, alert.timestamp_ns - _EVENT_LOOKBACK_NS),
            end_ns=alert.timestamp_ns + _EVENT_LOOKBACK_NS,
        )
        query = EventQuery(
            time_range=time_range,
            entity_uuid=alert.entity_uuid,
            page=1,
            limit=min(1000, max(self.cfg.explanation_max_contributing_events * 4, 16)),
        )
        page = await self.log_store.query_events(query)
        picked_events, events_truncated = _filter_events_by_ids(
            page.items,
            alert.contributing_events,
            self.cfg.explanation_max_contributing_events,
        )

        context = load_entity_baseline_context(
            entity_uuid=alert.entity_uuid,
            entity_value=alert.entity_value,
            entity_type=alert.entity_type,
            baseline_store=self.baseline_store,
        )
        prompt, prompt_truncated = build_prompt(
            alert,
            picked_events,
            context,
            max_prompt_chars=self.cfg.explanation_max_prompt_chars,
        )
        truncated = events_truncated or prompt_truncated

        t0 = time.monotonic()
        try:
            text = await asyncio.wait_for(
                self.backend.complete(
                    prompt,
                    max_tokens=self.cfg.max_tokens_default,
                    temperature=self.cfg.temperature_default,
                    stop=("\n\nALERT:",),
                ),
                timeout=self.cfg.explanation_timeout_s,
            )
        except TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            _log.error(
                "explanation: backend timeout alert_id=%s elapsed_ms=%.1f",
                alert_id,
                elapsed_ms,
            )
            raise
        except Exception:
            _log.error("explanation: backend failed alert_id=%s", alert_id, exc_info=True)
            raise
        latency_ms = (time.monotonic() - t0) * 1000.0

        parsed = parse_response(text)
        result = ExplanationResult(
            alert_id=alert_id,
            summary=parsed.summary,
            anomaly_rationale=parsed.anomaly_rationale,
            contributing_events=parsed.contributing_events,
            recommended_next_steps=parsed.recommended_next_steps,
            model=self.backend.name,
            generated_at_ns=time.time_ns(),
            latency_ms=latency_ms,
            cached=False,
            truncated=truncated,
        )
        await self.cache.put(alert_id, result)
        _log.debug("explanation: generated alert_id=%s latency_ms=%.1f", alert_id, latency_ms)
        return result
