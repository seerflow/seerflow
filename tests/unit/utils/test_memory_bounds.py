"""Unit tests for the in-process memory-bounds audit aggregator (S-082).

These tests prove the contract of ``collect_memory_bounds``: it is a pure
function that accepts every audited component as an optional keyword-only
argument and returns a stable JSON-serialisable shape suitable for the
``/api/v1/health`` envelope. Components that are not wired produce no key
in the result so the health endpoint can degrade gracefully.
"""

from __future__ import annotations

import pytest

from seerflow.utils.memory_bounds import (
    MemoryBoundsReport,
    collect_memory_bounds,
)


@pytest.mark.unit
def test_all_none_returns_empty_dict() -> None:
    """No components wired → no keys in the report."""
    assert collect_memory_bounds() == {}


@pytest.mark.unit
def test_typed_dict_shape_advertises_three_fields() -> None:
    """``MemoryBoundsReport`` must expose exactly ``current`` / ``max`` /
    ``evictions``. Dashboards key on these names; renaming is a breaking
    change for any downstream consumer.
    """
    assert set(MemoryBoundsReport.__annotations__) == {"current", "max", "evictions"}


@pytest.mark.unit
def test_unknown_kwargs_rejected() -> None:
    """Audit signature is closed — passing an unknown component name is a
    typo, not a silent skip."""
    with pytest.raises(TypeError):
        collect_memory_bounds(does_not_exist=object())  # type: ignore[call-arg]


@pytest.mark.unit
def test_receiver_manager_bounds() -> None:
    from seerflow.receivers.manager import ReceiverManager

    mgr = ReceiverManager(queue_maxsize=5)
    bounds = collect_memory_bounds(receiver_manager=mgr)
    assert bounds["receivers.queue"] == {"current": 0, "max": 5, "evictions": 0}


@pytest.mark.unit
def test_latency_tracker_bounds() -> None:
    from seerflow.api.latency import StageLatencyTracker

    tracker = StageLatencyTracker(maxlen=4, max_stages=2)
    for i in range(6):
        tracker.record("parse", float(i))
    bounds = collect_memory_bounds(latency_tracker=tracker)
    # 4 samples retained (deque maxlen=4), max envelope = 4 * 2 = 8.
    assert bounds["api.latency"] == {"current": 4, "max": 8, "evictions": 0}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregator_collects_every_component() -> None:
    """End-to-end coverage of every branch in ``collect_memory_bounds``.

    Builds a minimal instance of every audited component, passes them
    all to the aggregator, and asserts every documented key appears
    with the expected shape.
    """
    from dataclasses import dataclass

    from seerflow.alerting.dispatcher import AlertDispatcher
    from seerflow.alerting.sinks.otlp import OtlpSink
    from seerflow.alerting.sinks.pagerduty import PagerDutySink
    from seerflow.api.latency import StageLatencyTracker
    from seerflow.api.ws import ConnectionManager
    from seerflow.correlation.kill_chain import KillChainTracker
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.llm.explanation.cache import ExplanationCache
    from seerflow.llm.hunt.cache import HuntCache
    from seerflow.llm.rule_suggestion.cache import RuleSuggestionCache
    from seerflow.receivers.manager import ReceiverManager
    from seerflow.ueba.baseline import UEBAParams
    from seerflow.ueba.store import BaselineStore

    @dataclass(frozen=True)
    class _FakeKCConfig:
        enabled: bool = True
        tactic_threshold: int = 100
        window_seconds: int = 86400
        max_entities: int = 3

    class _S:
        pass

    components = {
        "baseline_store": BaselineStore(
            params=UEBAParams(
                alpha=0.05,
                source_ip_cap=4,
                template_top_k=4,
                warmup_days=0,
                warmup_min_events=0,
            ),
            max_entities=10,
        ),
        "window_buffer": EntityWindowBuffer(window_ns=10**9, max_events=10, max_entities=10),
        "risk_register": RiskRegister(half_life_ns=10**9, threshold=1.0, max_entities=10),
        "kill_chain": KillChainTracker(_FakeKCConfig()),  # type: ignore[arg-type]
        "receiver_manager": ReceiverManager(queue_maxsize=4),
        "alert_dispatcher": AlertDispatcher(
            targets=(),
            session=_S(),
            queue_maxsize=4,  # type: ignore[arg-type]
        ),
        "otlp_sink": OtlpSink(endpoint="", protocol="grpc", max_pending=4),
        "pagerduty_sink": PagerDutySink(
            routing_key="r",
            session=_S(),
            queue_maxsize=4,  # type: ignore[arg-type]
        ),
        "websocket_manager": ConnectionManager(max_connections=2, queue_maxlen=8),
        "latency_tracker": StageLatencyTracker(maxlen=8, max_stages=4),
        "explanation_cache": ExplanationCache(max_entries=10, ttl_seconds=3600),
        "hunt_cache": HuntCache(max_entries=10, ttl_seconds=3600),
        "rule_suggestion_cache": RuleSuggestionCache(max_entries=10, ttl_seconds=3600),
    }

    report = collect_memory_bounds(**components)  # type: ignore[arg-type]

    expected_keys = {
        "ueba.baselines",
        "correlation.window",
        "correlation.risk",
        "correlation.kill_chain",
        "receivers.queue",
        "alerting.dispatcher",
        "alerting.otlp",
        "alerting.pagerduty",
        "api.websocket",
        "api.latency",
        "llm.explanation_cache",
        "llm.hunt_cache",
        "llm.rule_suggestion_cache",
    }
    assert set(report) == expected_keys
    for key, row in report.items():
        assert set(row) == {"current", "max", "evictions"}, key
        assert row["current"] >= 0, key
        assert row["max"] >= 0, key
        assert row["evictions"] >= 0, key


@pytest.mark.unit
@pytest.mark.asyncio
async def test_alert_dispatcher_bounds_smoke() -> None:
    """``AlertDispatcher.bounds()`` is exposed; we don't actually fire the
    consumer loop (the audit is read-only).

    Build the dispatcher with a minimal stub session — the audit only
    reads queue depth / maxsize / drop counter.
    """
    from seerflow.alerting.dispatcher import AlertDispatcher

    class _FakeSession:
        pass

    dispatcher = AlertDispatcher(
        targets=(),
        session=_FakeSession(),  # type: ignore[arg-type]
        queue_maxsize=7,
    )
    bounds = collect_memory_bounds(alert_dispatcher=dispatcher)
    assert bounds["alerting.dispatcher"] == {"current": 0, "max": 7, "evictions": 0}
