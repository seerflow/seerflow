"""Unit tests for ``AlertExplanationService`` (S-071, Task 6)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from seerflow.config import LLMConfig
from seerflow.llm.explanation.cache import ExplanationCache
from seerflow.llm.explanation.service import AlertExplanationService
from tests.unit.llm.explanation._fakes import (
    FakeAlertStore,
    FakeLLMBackend,
    FakeLogStore,
    make_alert,
    make_event,
)


def _service(
    *,
    backend: FakeLLMBackend,
    alert: bool = True,
    events: tuple = (),
    cache: ExplanationCache | None = None,
    cfg: LLMConfig | None = None,
) -> tuple[AlertExplanationService, FakeAlertStore, FakeLogStore]:
    a = make_alert()
    alerts = (a,) if alert else ()
    alert_store = FakeAlertStore(alerts=alerts)
    log_store = FakeLogStore(events=events)
    cache = cache or ExplanationCache(max_entries=8, ttl_seconds=60)
    cfg = cfg or LLMConfig()
    service = AlertExplanationService(
        backend=backend,
        cache=cache,
        cfg=cfg,
        alert_store=alert_store,
        log_store=log_store,
        baseline_store=None,
    )
    return service, alert_store, log_store


@pytest.mark.unit
async def test_service_cache_miss_then_hit() -> None:
    backend = FakeLLMBackend()
    matching_event = make_event()
    service, _, _ = _service(backend=backend, events=(matching_event,))
    alert_id = make_alert().alert_id

    first = await service.explain(alert_id)
    second = await service.explain(alert_id)

    assert first is not None
    assert first.cached is False
    assert first.model == "fake_llm"
    assert backend.call_count == 1
    assert first.summary.startswith("Anomalous")
    assert first.recommended_next_steps == ("Reset alice's password",)

    assert second is not None
    assert second.cached is True
    # Backend not called again.
    assert backend.call_count == 1


@pytest.mark.unit
async def test_service_returns_none_for_unknown_alert() -> None:
    backend = FakeLLMBackend()
    service, _, _ = _service(backend=backend, alert=False)
    got = await service.explain(make_alert().alert_id)
    assert got is None
    assert backend.call_count == 0


@pytest.mark.unit
async def test_service_propagates_backend_exception_and_skips_cache() -> None:
    backend = FakeLLMBackend(raise_exc=RuntimeError("model died"))
    service, _, _ = _service(backend=backend, events=(make_event(),))
    with pytest.raises(RuntimeError):
        await service.explain(make_alert().alert_id)
    # Cache should be empty afterwards (no partial write).
    cached = await service.explain.__self__.cache.get(make_alert().alert_id)  # type: ignore[attr-defined]
    assert cached is None


@pytest.mark.unit
async def test_service_truncation_flag_propagates_when_events_missing() -> None:
    # Alert references three events; LogStore returns only one. The service
    # should mark the result as truncated.
    backend = FakeLLMBackend()
    alert = make_alert(
        contributing_events=(
            uuid.UUID("44444444-4444-4444-4444-444444444444"),
            uuid.UUID("55555555-5555-5555-5555-555555555555"),
            uuid.UUID("66666666-6666-6666-6666-666666666666"),
        )
    )
    # LogStore only returns one event with a different ID — it won't match.
    log_store_event = make_event(event_id=uuid.UUID("77777777-7777-7777-7777-777777777777"))
    alert_store = FakeAlertStore(alerts=(alert,))
    log_store = FakeLogStore(events=(log_store_event,))
    cache = ExplanationCache(max_entries=8, ttl_seconds=60)
    service = AlertExplanationService(
        backend=backend,
        cache=cache,
        cfg=LLMConfig(),
        alert_store=alert_store,
        log_store=log_store,
        baseline_store=None,
    )
    result = await service.explain(alert.alert_id)
    assert result is not None
    assert result.truncated is True


@pytest.mark.unit
async def test_service_times_out_on_slow_backend() -> None:
    backend = FakeLLMBackend(delay_s=5.0)
    cfg = LLMConfig(explanation_timeout_s=0.05)
    service, _, _ = _service(backend=backend, events=(make_event(),), cfg=cfg)
    with pytest.raises(asyncio.TimeoutError):
        await service.explain(make_alert().alert_id)


@pytest.mark.unit
async def test_service_records_latency_and_backend_name() -> None:
    backend = FakeLLMBackend()
    service, _, _ = _service(backend=backend, events=(make_event(),))
    result = await service.explain(make_alert().alert_id)
    assert result is not None
    assert result.model == "fake_llm"
    assert result.latency_ms >= 0.0


@pytest.mark.unit
async def test_service_caps_contributing_events() -> None:
    """Service should pass at most ``explanation_max_contributing_events`` to the prompt."""
    backend = FakeLLMBackend()
    # Build an alert referencing 5 events; cap at 2 via config.
    ids = tuple(uuid.UUID(int=i + 100) for i in range(5))
    alert = make_alert(contributing_events=ids)
    log_events = tuple(make_event(event_id=eid) for eid in ids)
    alert_store = FakeAlertStore(alerts=(alert,))
    log_store = FakeLogStore(events=log_events)
    cfg = LLMConfig(explanation_max_contributing_events=2)
    cache = ExplanationCache(max_entries=4, ttl_seconds=60)
    service = AlertExplanationService(
        backend=backend,
        cache=cache,
        cfg=cfg,
        alert_store=alert_store,
        log_store=log_store,
        baseline_store=None,
    )
    result = await service.explain(alert.alert_id)
    assert result is not None
    # Prompt sent to backend should reference at most 2 events.
    assert backend.last_args is not None
    prompt = str(backend.last_args["prompt"])
    bullet_count = prompt.count("\n- [")
    assert bullet_count == 2
    # And the result should flag truncation because we kept fewer than the
    # alert's full contributing-events tuple.
    assert result.truncated is True
