"""``RuleSuggestionService`` orchestrator (S-100, FR-066).

Mirrors :class:`seerflow.llm.explanation.service.AlertExplanationService`:

1. Listing eligible patterns is a thin wrapper around
   :func:`seerflow.llm.rule_suggestion.aggregator.count_pattern_tps`.
2. ``suggest(pattern_key)`` orchestrates the cache → eligibility re-check →
   prompt build → LLM call → YAML extraction → SigmaHQ validation → cache
   put.

The service surfaces the validator's three-stage verdict on the
``RuleSuggestionResult`` so the dashboard's Monaco editor can show "fix
the YAML" hints without the operator losing the draft. Backend exceptions
(including ``asyncio.TimeoutError``) propagate — the route layer
translates them to HTTP 502.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from seerflow.llm.rule_suggestion.aggregator import count_pattern_tps
from seerflow.llm.rule_suggestion.parser import extract_yaml
from seerflow.llm.rule_suggestion.prompt import build_prompt
from seerflow.llm.rule_suggestion.result import RuleSuggestionResult
from seerflow.models.query import EventQuery, TimeRange
from seerflow.sigma.validator import SigmaRuleValidationError, validate_yaml

if TYPE_CHECKING:
    import uuid

    from seerflow.config import LLMConfig
    from seerflow.llm.protocol import LLMBackend
    from seerflow.llm.rule_suggestion.aggregator import PatternFeedbackRow
    from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
    from seerflow.models.alert import Alert
    from seerflow.models.event import SeerflowEvent
    from seerflow.storage.protocols import AlertStore, LogStore

_log = logging.getLogger(__name__)


# Time window opened around each sample alert when fetching its
# representative contributing event. Wide enough to catch the original
# event even with modest clock drift; narrow enough to keep the query cheap.
_EVENT_LOOKBACK_NS = 24 * 3_600 * 1_000_000_000  # 24 hours

# Hard cap on max_tokens the service ever asks for. The LLM backend
# enforces its own cap (S-070, 1024); this matches it so a malformed
# config cannot bypass the backend's defensive ceiling.
_HARD_MAX_TOKENS = 1024

# How many TP-confirmed sample alerts the prompt builder receives. Cap of
# 4 keeps the prompt budget bounded; the aggregator caps at 16 IDs and we
# select the newest four below.
_MAX_SAMPLE_ALERTS = 4


def _pattern_window_ns(cfg: LLMConfig) -> int | None:
    """Convert ``cfg.rule_suggestion_window_days`` to a ns window."""
    days = cfg.rule_suggestion_window_days
    if days <= 0:
        return None
    return days * 24 * 3_600 * 1_000_000_000


def _validation_verdict(yaml_text: str) -> tuple[str, str, str, tuple[str, ...]]:
    """Run the SigmaHQ validator over ``yaml_text``.

    Returns a 4-tuple ``(stage, message, title, logsource_key)`` where
    ``stage`` is one of ``"ok"``, ``"yaml"``, ``"schema"``, ``"compile"``.
    On ``stage == "ok"`` the ``title`` and ``logsource_key`` are pulled from
    the parsed rule; on failure both are empty.
    """
    if not yaml_text or not yaml_text.strip():
        return "yaml", "empty completion", "", ()
    try:
        rule = validate_yaml(yaml_text)
    except SigmaRuleValidationError as exc:
        return exc.stage, exc.message, "", ()
    # ``validate_yaml`` applies the seerflow pipeline; ``rule.title`` and
    # the logsource attributes are populated on success.
    title = getattr(rule, "title", "") or ""
    logsource = getattr(rule, "logsource", None)
    logsource_key: tuple[str, ...] = ()
    if logsource is not None:
        parts = [getattr(logsource, attr, None) for attr in ("category", "product", "service")]
        logsource_key = tuple(p for p in parts if p)
    return "ok", "", title, logsource_key


class RuleSuggestionService:
    """Orchestrate Sigma rule suggestion generation from TP feedback."""

    def __init__(
        self,
        *,
        backend: LLMBackend,
        cache: RuleSuggestionCache,
        cfg: LLMConfig,
        alert_store: AlertStore,
        log_store: LogStore,
    ) -> None:
        self.backend = backend
        self.cache = cache
        self.cfg = cfg
        self.alert_store = alert_store
        self.log_store = log_store

    async def list_eligible_patterns(self) -> tuple[PatternFeedbackRow, ...]:
        """Return patterns meeting ``cfg.rule_suggestion_min_tp``.

        Forwarded directly from ``aggregator.count_pattern_tps`` — no
        in-memory filtering. The aggregator returns rows ordered
        ``tp_count DESC, most_recent_tp_ns DESC``.
        """
        return await count_pattern_tps(
            self.alert_store,
            min_tp=self.cfg.rule_suggestion_min_tp,
            window_ns=_pattern_window_ns(self.cfg),
        )

    async def suggest(self, pattern_key: str) -> RuleSuggestionResult | None:
        """Return a (cached or freshly generated) suggestion.

        Returns ``None`` when the pattern is no longer eligible (operator
        may have deleted feedback). Re-raises any backend exception,
        including ``asyncio.TimeoutError`` from the wall-clock guard.
        """
        cached = await self.cache.get(pattern_key)
        if cached is not None:
            _log.debug("rule_suggestion: cache hit pattern_key=%s", pattern_key)
            return cached

        # Re-check eligibility — the operator may have purged feedback
        # between the dashboard's list call and this suggest call.
        eligible = await self.list_eligible_patterns()
        target: PatternFeedbackRow | None = next(
            (row for row in eligible if row.pattern_key == pattern_key), None
        )
        if target is None:
            return None

        sample_alerts = await self._load_sample_alerts(target)
        sample_events = await self._load_sample_events(sample_alerts)
        prompt, _truncated = build_prompt(pattern_key, sample_alerts, sample_events)

        max_tokens = min(self.cfg.max_tokens_default, _HARD_MAX_TOKENS)
        t0 = time.monotonic()
        try:
            text = await asyncio.wait_for(
                self.backend.complete(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=self.cfg.temperature_default,
                    stop=(),
                ),
                timeout=self.cfg.rule_suggestion_timeout_s,
            )
        except TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            _log.warning(
                "rule_suggestion: backend timeout pattern_key=%s elapsed_ms=%.1f",
                pattern_key,
                elapsed_ms,
            )
            raise
        latency_ms = (time.monotonic() - t0) * 1000.0

        yaml_body = extract_yaml(text)
        stage, message, title, logsource_key = _validation_verdict(yaml_body)
        result = RuleSuggestionResult(
            pattern_key=pattern_key,
            tp_count=target.tp_count,
            yaml=yaml_body,
            title=title,
            logsource_key=logsource_key,
            validation_stage=stage,  # type: ignore[arg-type]
            validation_message=message,
            contributing_alert_ids=target.contributing_alert_ids,
            model=self.backend.name,
            generated_at_ns=time.time_ns(),
            latency_ms=latency_ms,
            cached=False,
        )
        await self.cache.put(pattern_key, result)
        _log.debug(
            "rule_suggestion: generated pattern_key=%s latency_ms=%.1f stage=%s",
            pattern_key,
            latency_ms,
            stage,
        )
        return result

    async def invalidate(self, pattern_key: str) -> None:
        """Drop the cached suggestion for ``pattern_key``.

        Idempotent: never raises, no-op when the entry was never cached.
        Used by the API route after the operator promotes the suggested
        rule via ``POST /api/v1/sigma/rules`` so the dashboard does not
        keep surfacing a pattern that is now codified.
        """
        await self.cache.delete(pattern_key)

    async def _load_sample_alerts(self, target: PatternFeedbackRow) -> tuple[Alert, ...]:
        """Fetch up to four newest TP-confirmed alerts for the prompt."""
        ids = target.contributing_alert_ids[:_MAX_SAMPLE_ALERTS]
        out: list[Alert] = []
        for alert_id in ids:
            alert = await self.alert_store.get_alert_by_id(alert_id)
            if alert is not None:
                out.append(alert)
        return tuple(out)

    async def _load_sample_events(self, alerts: tuple[Alert, ...]) -> tuple[SeerflowEvent, ...]:
        """Fetch one representative contributing event per sample alert.

        Skips alerts whose ``contributing_events`` tuple is empty (older
        alerts) — the prompt builder tolerates fewer events than alerts.
        """
        if not alerts:
            return ()

        target_event_ids: set[uuid.UUID] = set()
        time_lo = float("inf")
        time_hi = 0
        for alert in alerts:
            if not alert.contributing_events:
                continue
            target_event_ids.add(alert.contributing_events[0])
            time_lo = min(time_lo, alert.timestamp_ns - _EVENT_LOOKBACK_NS)
            time_hi = max(time_hi, alert.timestamp_ns + _EVENT_LOOKBACK_NS)

        if not target_event_ids:
            return ()

        time_range = TimeRange(
            start_ns=max(0, int(time_lo)),
            end_ns=int(time_hi),
        )
        page = await self.log_store.query_events(
            EventQuery(
                time_range=time_range,
                page=1,
                limit=max(16, len(target_event_ids) * 4),
            )
        )
        # Keep one event per sample alert by matching ``event_id``. Stable
        # ordering: align with the alerts argument (which is newest-first).
        picked: list[SeerflowEvent] = []
        for alert in alerts:
            if not alert.contributing_events:
                continue
            wanted = alert.contributing_events[0]
            for evt in page.items:
                if evt.event_id == wanted:
                    picked.append(evt)
                    break
        return tuple(picked)
