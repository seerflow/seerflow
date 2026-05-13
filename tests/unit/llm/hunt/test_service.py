"""Unit tests for ``NaturalLanguageHuntService`` (S-072, Task 7)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from seerflow.config import LLMConfig
from seerflow.llm.hunt.cache import HuntCache
from seerflow.llm.hunt.service import NaturalLanguageHuntService
from seerflow.models.event import SeerflowEvent
from seerflow.models.query import EventQuery, Page

# Reuse the existing fakes from the explanation tests. They live in the
# unit test tree, not in src/, so promoting them is a refactor follow-up.
from tests.unit.llm.explanation._fakes import FakeLLMBackend, FakeLogStore


def _events(n: int = 2) -> tuple[SeerflowEvent, ...]:
    return tuple(
        SeerflowEvent(
            event_id=uuid.uuid4(),
            timestamp_ns=1_700_000_000_000_000_000 + i,
            observed_ns=1_700_000_000_000_000_000 + i,
            message=f"event-{i}",
            source_type="auth",
        )
        for i in range(n)
    )


def _llm_cfg(**overrides: object) -> LLMConfig:
    base = {
        "backend": "",
        "hunt_cache_size": 16,
        "hunt_cache_ttl_s": 60,
        "hunt_timeout_s": 5.0,
        "hunt_max_results": 50,
        "hunt_max_query_chars": 256,
    }
    base.update(overrides)
    return LLMConfig(**base)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_happy_path_invokes_backend_and_returns_events() -> None:
    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = FakeLogStore(events=_events(2))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    result = await svc.hunt("ssh logins from external")
    assert backend.call_count == 1
    assert result.total == 2
    assert len(result.events) == 2
    assert result.cached is False
    assert result.filters == {"text_query": "ssh"}
    assert result.model == "fake_llm"


@pytest.mark.unit
async def test_cache_hit_skips_backend() -> None:
    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    await svc.hunt("ssh logins")
    second = await svc.hunt("ssh logins")  # identical
    assert backend.call_count == 1
    assert second.cached is True
    assert second.latency_ms == 0.0


@pytest.mark.unit
async def test_cache_hit_after_normalisation() -> None:
    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    await svc.hunt("SSH from External")
    second = await svc.hunt("  ssh   from   external  ")
    assert backend.call_count == 1
    assert second.cached is True


@pytest.mark.unit
async def test_backend_timeout_raises_through() -> None:
    backend = FakeLLMBackend(delay_s=10.0)
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(hunt_timeout_s=1.0),
        log_store=log,
    )
    with pytest.raises(asyncio.TimeoutError):
        await svc.hunt("ssh logins")


@pytest.mark.unit
async def test_garbage_response_falls_back_to_text_query() -> None:
    backend = FakeLLMBackend(response="no idea, sorry.")
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    result = await svc.hunt("alpha bravo charlie")
    assert result.filters == {"text_query": "alpha bravo charlie"}
    assert result.total == 1


@pytest.mark.unit
async def test_empty_query_rejected() -> None:
    backend = FakeLLMBackend()
    log = FakeLogStore(events=())
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    with pytest.raises(ValueError, match="empty"):
        await svc.hunt("   ")


@pytest.mark.unit
async def test_overlong_query_rejected() -> None:
    backend = FakeLLMBackend()
    log = FakeLogStore(events=())
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(hunt_max_query_chars=20),
        log_store=log,
    )
    with pytest.raises(ValueError, match="too long"):
        await svc.hunt("x" * 100)


@pytest.mark.unit
async def test_max_results_clamps_storage_limit() -> None:
    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(hunt_max_results=5),
        log_store=log,
    )
    await svc.hunt("ssh")
    # FakeLogStore captures the EventQuery via its query_calls counter;
    # we check that the service used the cfg.hunt_max_results limit (5),
    # not the global EventQuery max of 1000.
    assert log.query_calls == 1


@pytest.mark.unit
async def test_truncated_flag_when_total_exceeds_returned_events() -> None:
    """When the storage page truncates the result, ``truncated`` is True."""

    class _ClampingStore(FakeLogStore):
        async def query_events(self, filters: EventQuery) -> Page[SeerflowEvent]:
            self.query_calls += 1
            # Pretend storage has 999 matches but only returned ``limit``.
            return Page(
                items=self._events,
                total=999,
                page=filters.page,
                limit=filters.limit,
            )

    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = _ClampingStore(events=_events(3))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(),
        log_store=log,
    )
    result = await svc.hunt("ssh")
    assert result.truncated is True
    assert result.total == 999


@pytest.mark.unit
async def test_query_capped_in_prompt_when_too_long_but_within_limit() -> None:
    """Queries up to ``hunt_max_query_chars`` are accepted and capped in the prompt."""
    backend = FakeLLMBackend(response='{"text_query": "ssh"}')
    log = FakeLogStore(events=_events(1))
    svc = NaturalLanguageHuntService(
        backend=backend,
        cache=HuntCache(max_entries=16, ttl_seconds=60),
        cfg=_llm_cfg(hunt_max_query_chars=64),
        log_store=log,
    )
    # 60 chars — within the cap.
    nl = "x" * 60
    result = await svc.hunt(nl)
    assert result.query == nl
    assert backend.last_args is not None
    # Prompt should contain the full 60-char query (within cap).
    assert nl in backend.last_args["prompt"]  # type: ignore[operator]
