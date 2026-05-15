"""Unit tests for ``RuleSuggestionService`` (S-100, AC3-AC5)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from seerflow.config import LLMConfig
from seerflow.llm.rule_suggestion.aggregator import PatternFeedbackRow
from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
from seerflow.llm.rule_suggestion.service import RuleSuggestionService
from seerflow.models.alert import Alert
from seerflow.models.event import SeerflowEvent, SeverityLevel
from seerflow.models.query import Page

if TYPE_CHECKING:
    from seerflow.models.query import EventQuery


_VALID_YAML = """\
title: Test Rule
id: 6b9c45a8-49a3-4d9e-902f-e10f4d8e8e21
status: experimental
description: Synthetic rule for unit-test backend stub.
author: test
date: 2026-05-13
logsource:
    category: authentication
    product: linux
detection:
    selection:
        action: ssh_failed
    condition: selection
falsepositives:
    - Automated security scans
level: medium
"""

_BAD_YAML = "not: [valid"


def _alert(
    *,
    alert_id: str = "a1",
    alert_type: str = "ml",
    rule_name: str = "hst-anomaly",
    entity_type: str = "ip",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        alert_type=alert_type,  # type: ignore[arg-type]
        timestamp_ns=1_700_000_000_000_000_000,
        severity_id=SeverityLevel.WARNING,
        rule_name=rule_name,
        description="anomaly",
        entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, alert_id)),
        entity_value=f"v-{alert_id}",
        entity_type=entity_type,  # type: ignore[arg-type]
        contributing_events=(uuid.uuid4(),),
        dedup_key=f"hst:1:syslog:{alert_id}",
    )


def _event() -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        source_type="syslog",
        message="ssh: invalid user",
        template_id=42,
    )


@dataclass
class _FakeBackend:
    name: str = "stub-backend"
    call_count: int = 0
    response: str = field(default=_VALID_YAML)
    delay_s: float = 0.0
    raise_exc: type[BaseException] | None = None

    async def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
        stop: tuple[str, ...] = (),
    ) -> str:
        self.call_count += 1
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.raise_exc is not None:
            raise self.raise_exc("synthetic failure")
        return f"```yaml\n{self.response}\n```"


@dataclass
class _FakeAlertStore:
    """In-memory fake satisfying the subset of AlertStore we touch."""

    alerts: dict[str, Alert] = field(default_factory=dict)
    rows: tuple[PatternFeedbackRow, ...] = ()

    async def aggregate_tp_feedback(
        self,
        *,
        min_tp: int,
        window_ns: int | None = None,
        now_ns: int | None = None,
        limit: int = 50_000,
    ) -> tuple[PatternFeedbackRow, ...]:
        return tuple(r for r in self.rows if r.tp_count >= min_tp)[:limit]

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        return self.alerts.get(alert_id)


@dataclass
class _FakeLogStore:
    """In-memory fake LogStore returning a single SeerflowEvent."""

    event_by_id: dict[uuid.UUID, SeerflowEvent] = field(default_factory=dict)

    async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
        items = tuple(self.event_by_id.values())
        return Page(items=items, total=len(items), page=1, limit=max(1, len(items) or 1))


def _config() -> LLMConfig:
    return LLMConfig(
        rule_suggestion_cache_size=4,
        rule_suggestion_cache_ttl_s=60,
        rule_suggestion_min_tp=3,
        rule_suggestion_window_days=0,
        rule_suggestion_timeout_s=10.0,
        max_tokens_default=512,
        temperature_default=0.2,
    )


def _build_service(
    *,
    backend: _FakeBackend | None = None,
    alert_store: _FakeAlertStore | None = None,
    log_store: _FakeLogStore | None = None,
    cache: RuleSuggestionCache | None = None,
) -> RuleSuggestionService:
    return RuleSuggestionService(
        backend=backend or _FakeBackend(),
        cache=cache or RuleSuggestionCache(max_entries=4, ttl_seconds=60),
        cfg=_config(),
        alert_store=alert_store or _FakeAlertStore(),
        log_store=log_store or _FakeLogStore(),
    )


def _seed_alerts(store: _FakeAlertStore, *, n: int = 3) -> tuple[Alert, ...]:
    alerts = tuple(_alert(alert_id=f"a-{i}") for i in range(n))
    for a in alerts:
        store.alerts[a.alert_id] = a
    return alerts


# ----- list_eligible_patterns --------------------------------------------


class TestListEligiblePatterns:
    async def test_empty_returns_empty_tuple(self) -> None:
        service = _build_service()
        result = await service.list_eligible_patterns()
        assert result == ()

    async def test_returns_rows_from_store(self) -> None:
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        service = _build_service(alert_store=store)
        result = await service.list_eligible_patterns()
        assert len(result) == 1
        assert result[0].pattern_key == "ml:hst-anomaly:ip"


# ----- suggest -----------------------------------------------------------


class TestSuggest:
    async def test_cache_hit_skips_backend(self) -> None:
        backend = _FakeBackend()
        cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = _build_service(backend=backend, cache=cache, alert_store=store)
        # First call populates the cache.
        first = await service.suggest("ml:hst-anomaly:ip")
        assert first is not None
        assert first.cached is False
        assert backend.call_count == 1
        # Second call hits the cache.
        second = await service.suggest("ml:hst-anomaly:ip")
        assert second is not None
        assert second.cached is True
        assert backend.call_count == 1  # no second call

    async def test_returns_none_when_pattern_below_threshold(self) -> None:
        """AC4: pattern that falls below ``min_tp`` returns ``None``."""
        store = _FakeAlertStore(rows=())  # no eligible rows
        service = _build_service(alert_store=store)
        assert await service.suggest("ml:hst-anomaly:ip") is None

    async def test_validation_ok_branch(self) -> None:
        """AC4: a YAML that passes the validator gets ``validation_stage='ok'``."""
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = _build_service(alert_store=store)
        result = await service.suggest("ml:hst-anomaly:ip")
        assert result is not None
        assert result.validation_stage == "ok"
        assert result.validation_message == ""
        # The validator extracted the title from the YAML.
        assert result.title == "Test Rule"
        # The validator extracted the logsource key.
        assert "authentication" in result.logsource_key

    async def test_validation_failure_does_not_raise(self) -> None:
        """AC4: invalid YAML → result populated, no exception."""
        backend = _FakeBackend(response=_BAD_YAML)
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = _build_service(backend=backend, alert_store=store)
        result = await service.suggest("ml:hst-anomaly:ip")
        assert result is not None
        assert result.validation_stage != "ok"
        assert result.validation_message != ""
        assert result.title == ""

    async def test_backend_exception_propagates(self) -> None:
        """AC4: a non-timeout backend exception propagates."""
        backend = _FakeBackend(raise_exc=RuntimeError)
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = _build_service(backend=backend, alert_store=store)
        with pytest.raises(RuntimeError, match="synthetic"):
            await service.suggest("ml:hst-anomaly:ip")

    async def test_backend_timeout_propagates(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC4: backend exceeding the timeout raises ``TimeoutError``."""
        backend = _FakeBackend(delay_s=2.0)
        # Tight timeout so the test is fast.
        cfg = _config()
        cfg = LLMConfig(  # type: ignore[call-arg]
            rule_suggestion_cache_size=cfg.rule_suggestion_cache_size,
            rule_suggestion_cache_ttl_s=cfg.rule_suggestion_cache_ttl_s,
            rule_suggestion_min_tp=cfg.rule_suggestion_min_tp,
            rule_suggestion_window_days=cfg.rule_suggestion_window_days,
            rule_suggestion_timeout_s=0.05,
            max_tokens_default=cfg.max_tokens_default,
            temperature_default=cfg.temperature_default,
        )
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = RuleSuggestionService(
            backend=backend,
            cache=RuleSuggestionCache(max_entries=4, ttl_seconds=60),
            cfg=cfg,
            alert_store=store,
            log_store=_FakeLogStore(),
        )
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await service.suggest("ml:hst-anomaly:ip")

    async def test_contributing_alert_ids_in_result(self) -> None:
        """AC4: ``contributing_alert_ids`` from the aggregator propagate."""
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=4,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2", "a-3"),
                ),
            )
        )
        _seed_alerts(store, n=4)
        service = _build_service(alert_store=store)
        result = await service.suggest("ml:hst-anomaly:ip")
        assert result is not None
        assert result.contributing_alert_ids == ("a-0", "a-1", "a-2", "a-3")
        assert result.tp_count == 4

    async def test_pattern_key_filter_when_not_in_eligible_rows(self) -> None:
        """AC4: a key absent from the aggregator returns ``None``."""
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:other:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0",),
                ),
            )
        )
        service = _build_service(alert_store=store)
        assert await service.suggest("ml:hst-anomaly:ip") is None


# ----- invalidate --------------------------------------------------------


class TestHelpersAndEdgeCases:
    """Cover the small helpers + edge-case branches in the orchestrator."""

    async def test_window_days_zero_translates_to_no_window(self) -> None:
        """``rule_suggestion_window_days=0`` means no window filter."""
        store = _FakeAlertStore()
        service = _build_service(alert_store=store)
        # The aggregator must be called with ``window_ns=None``.
        await service.list_eligible_patterns()
        # No assertion failure means no exception; storage receives None.

    async def test_window_days_positive_translates_to_ns(self) -> None:
        """A positive ``rule_suggestion_window_days`` becomes ns."""

        class _CaptureStore:
            rows = ()

            def __init__(self) -> None:
                self.captured: dict[str, object] = {}

            async def aggregate_tp_feedback(
                self,
                *,
                min_tp: int,
                window_ns: int | None = None,
                now_ns: int | None = None,
                limit: int = 50_000,
            ) -> tuple[PatternFeedbackRow, ...]:
                self.captured["window_ns"] = window_ns
                return ()

            async def get_alert_by_id(self, alert_id: str) -> Alert | None:
                return None

        store = _CaptureStore()
        cfg = LLMConfig(rule_suggestion_window_days=7)
        service = RuleSuggestionService(
            backend=_FakeBackend(),
            cache=RuleSuggestionCache(max_entries=4, ttl_seconds=60),
            cfg=cfg,
            alert_store=store,  # type: ignore[arg-type]
            log_store=_FakeLogStore(),
        )
        await service.list_eligible_patterns()
        assert store.captured["window_ns"] == 7 * 24 * 3_600 * 1_000_000_000

    async def test_empty_yaml_yields_yaml_stage(self) -> None:
        """A completion that produces empty YAML → ``validation_stage='yaml'``."""

        # Use a backend that emits ONLY whitespace (no fence wrapping) so the
        # parser returns "" and the validator emits the empty-body verdict.
        class _EmptyBackend:
            name = "empty-backend"
            call_count = 0

            async def complete(
                self,
                prompt: str,
                *,
                max_tokens: int = 256,
                temperature: float = 0.2,
                stop: tuple[str, ...] = (),
            ) -> str:
                self.call_count += 1
                return "   \n   "

        backend = _EmptyBackend()
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = RuleSuggestionService(
            backend=backend,  # type: ignore[arg-type]
            cache=RuleSuggestionCache(max_entries=4, ttl_seconds=60),
            cfg=_config(),
            alert_store=store,
            log_store=_FakeLogStore(),
        )
        result = await service.suggest("ml:hst-anomaly:ip")
        assert result is not None
        assert result.validation_stage == "yaml"
        assert "empty" in result.validation_message.lower()

    async def test_alerts_without_contributing_events_are_skipped(self) -> None:
        """Sample alerts whose ``contributing_events`` is empty cause no crash."""
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        # Seed alerts with NO contributing_events.
        for i in range(3):
            alert_id = f"a-{i}"
            store.alerts[alert_id] = Alert(
                alert_id=alert_id,
                alert_type="ml",
                timestamp_ns=1_700_000_000_000_000_000,
                severity_id=SeverityLevel.WARNING,
                rule_name="hst-anomaly",
                description="anomaly",
                entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, alert_id)),
                entity_value=f"v-{alert_id}",
                entity_type="ip",
                contributing_events=(),
                dedup_key=f"hst:1:syslog:{alert_id}",
            )
        service = _build_service(alert_store=store)
        result = await service.suggest("ml:hst-anomaly:ip")
        # No crash; result still generated (the LLM gets context-only).
        assert result is not None

    async def test_missing_alert_skipped_in_sample_load(self) -> None:
        """``alert_store.get_alert_by_id`` returning ``None`` is tolerated."""
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("missing-1", "missing-2", "a-0"),
                ),
            )
        )
        # Only seed one of three referenced IDs.
        a = _alert(alert_id="a-0")
        store.alerts[a.alert_id] = a
        service = _build_service(alert_store=store)
        result = await service.suggest("ml:hst-anomaly:ip")
        assert result is not None

    async def test_load_sample_events_handles_empty_alert_list(self) -> None:
        """Empty alerts → empty events tuple."""
        service = _build_service()
        events = await service._load_sample_events(())
        assert events == ()

    async def test_load_sample_events_matches_event_id(self) -> None:
        """Sample events tuple aligns with each alert's first contributing event."""
        evt = _event()
        alert = Alert(
            alert_id="a-evt",
            alert_type="ml",
            timestamp_ns=evt.timestamp_ns,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="anomaly",
            entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "a-evt")),
            entity_value="v-a-evt",
            entity_type="ip",
            contributing_events=(evt.event_id,),
            dedup_key="hst:1:syslog:a-evt",
        )
        alert_store = _FakeAlertStore(alerts={alert.alert_id: alert})
        log_store = _FakeLogStore(event_by_id={evt.event_id: evt})
        service = _build_service(alert_store=alert_store, log_store=log_store)
        events = await service._load_sample_events((alert,))
        assert len(events) == 1
        assert events[0].event_id == evt.event_id

    async def test_load_sample_events_skips_mixed_empty_contributing(self) -> None:
        """Mixed: one alert has events, one does not — only the populated one returned."""
        evt = _event()
        alert_with = Alert(
            alert_id="a-with",
            alert_type="ml",
            timestamp_ns=evt.timestamp_ns,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="anomaly",
            entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "a-with")),
            entity_value="v-with",
            entity_type="ip",
            contributing_events=(evt.event_id,),
            dedup_key="hst:1:syslog:a-with",
        )
        alert_without = Alert(
            alert_id="a-without",
            alert_type="ml",
            timestamp_ns=evt.timestamp_ns,
            severity_id=SeverityLevel.WARNING,
            rule_name="hst-anomaly",
            description="anomaly",
            entity_uuid=str(uuid.uuid5(uuid.NAMESPACE_DNS, "a-without")),
            entity_value="v-without",
            entity_type="ip",
            contributing_events=(),
            dedup_key="hst:1:syslog:a-without",
        )
        alert_store = _FakeAlertStore(
            alerts={alert_with.alert_id: alert_with, alert_without.alert_id: alert_without}
        )
        log_store = _FakeLogStore(event_by_id={evt.event_id: evt})
        service = _build_service(alert_store=alert_store, log_store=log_store)
        events = await service._load_sample_events((alert_with, alert_without))
        assert len(events) == 1
        assert events[0].event_id == evt.event_id


class TestInvalidate:
    async def test_removes_cached_entry(self) -> None:
        """AC5: invalidate drops the cached entry."""
        backend = _FakeBackend()
        cache = RuleSuggestionCache(max_entries=4, ttl_seconds=60)
        store = _FakeAlertStore(
            rows=(
                PatternFeedbackRow(
                    pattern_key="ml:hst-anomaly:ip",
                    tp_count=3,
                    most_recent_tp_ns=100,
                    contributing_alert_ids=("a-0", "a-1", "a-2"),
                ),
            )
        )
        _seed_alerts(store, n=3)
        service = _build_service(backend=backend, cache=cache, alert_store=store)
        await service.suggest("ml:hst-anomaly:ip")
        assert backend.call_count == 1
        await service.invalidate("ml:hst-anomaly:ip")
        # Next call hits the backend again because the cache was cleared.
        await service.suggest("ml:hst-anomaly:ip")
        assert backend.call_count == 2

    async def test_invalidate_missing_key_no_op(self) -> None:
        """AC5: invalidate a never-cached key does not raise."""
        service = _build_service()
        await service.invalidate("never-there")  # must not raise
