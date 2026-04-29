"""Unit tests for IoCMatcher (S-068)."""

from __future__ import annotations

import asyncio
import random
import threading
import uuid
from typing import TYPE_CHECKING

import msgspec
import pytest

from seerflow.config import IoCMatcherConfig, TAXIIFeedConfig, ThreatIntelConfig
from seerflow.models.event import SeerflowEvent
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.threat_intel.matcher import (
    IoCMatcher,
    IoCMatcherMetrics,
)

if TYPE_CHECKING:
    from seerflow.models.ioc_match import IoCMatch


@pytest.fixture
def stub_store() -> object:
    class _Store:
        async def save_state(self, key: str, data: bytes) -> None:
            return None

        async def load_state(self, key: str) -> bytes | None:
            return None

        async def delete_state(self, key: str) -> None:
            return None

    return _Store()


def test_initial_metrics_are_zero(stub_store: object) -> None:
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))
    matcher = IoCMatcher(config=cfg, model_store=stub_store)  # type: ignore[arg-type]
    snap = matcher.metrics_snapshot()
    assert isinstance(snap, IoCMatcherMetrics)
    assert snap.rebuild_count == 0
    assert snap.checks_total == 0
    assert snap.bloom_hits_total == 0
    assert snap.confirmed_matches_total == 0
    assert snap.false_positives_total == 0
    assert snap.last_rebuild_at_ns is None
    assert snap.indicators_loaded == {}


class _MemStore:
    """Async in-memory ModelStore for tests."""

    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}

    async def save_state(self, key: str, data: bytes) -> None:
        self._kv[key] = bytes(data)

    async def load_state(self, key: str) -> bytes | None:
        return self._kv.get(key)

    async def delete_state(self, key: str) -> None:
        self._kv.pop(key, None)


def _ipv4(value: str, *, source: str = "f1", confidence: int = 80) -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed=source,
        confidence=confidence,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


@pytest.mark.asyncio
async def test_refresh_loads_from_single_feed_snapshot() -> None:
    store = _MemStore()
    feed = TAXIIFeedConfig(id="f1", url="https://x", collection_id="c")
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=(feed,),
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    snap_metrics = matcher.metrics_snapshot()
    assert snap_metrics.rebuild_count == 1
    assert snap_metrics.indicators_loaded == {"ipv4": 1}
    assert snap_metrics.bit_array_bytes > 0
    assert snap_metrics.last_rebuild_at_ns is not None


@pytest.mark.asyncio
async def test_refresh_unions_multiple_feeds() -> None:
    store = _MemStore()
    feeds = (
        TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),
        TAXIIFeedConfig(id="f2", url="https://y", collection_id="d"),
    )
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    for fid, val in (("f1", "1.2.3.4"), ("f2", "5.6.7.8")):
        s = IndicatorSnapshot(
            feed_id=fid,
            fetched_at_ns=1,
            indicators=(_ipv4(val, source=fid),),
            cursor=None,
        )
        await store.save_state(f"taxii:snapshot:{fid}", msgspec.msgpack.encode(s))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 2}


@pytest.mark.asyncio
async def test_refresh_filters_by_confidence_floor() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, confidence_floor=50),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            _ipv4("1.2.3.4", confidence=80),
            _ipv4("9.9.9.9", confidence=10),  # below floor
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 1}


@pytest.mark.asyncio
async def test_refresh_skips_disabled_types() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, enabled_types=("domain",)),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),  # ipv4 disabled
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.metrics_snapshot().indicators_loaded == {}


@pytest.mark.asyncio
async def test_check_returns_indicator_for_known_value() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    hit = matcher.check("1.2.3.4", "ipv4")
    assert hit is not None
    assert hit.value == "1.2.3.4"
    assert matcher.check("9.9.9.9", "ipv4") is None
    metrics = matcher.metrics_snapshot()
    assert metrics.checks_total == 2
    assert metrics.confirmed_matches_total == 1


@pytest.mark.asyncio
async def test_check_returns_none_for_disabled_type() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, enabled_types=("domain",)),
    )
    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.check("1.2.3.4", "ipv4") is None  # type disabled


@pytest.mark.asyncio
async def test_false_positive_metric_increments_on_bloom_collision() -> None:
    """Brute-force a Bloom collision in a tiny high-FPR filter."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    # Tiny bloom + high FPR so collisions are easy to find.
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, fpr=0.5, min_capacity=10),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()

    rng = random.Random(0xBADC0FFEE)  # noqa: S311 — deterministic test RNG, not crypto
    collision: str | None = None
    for _ in range(10_000):
        candidate = f"{rng.randrange(0, 1 << 32):08x}"
        # We want a value where the Bloom probes True but the dict lacks it.
        state = matcher._state
        assert state is not None
        if candidate in state.bloom and candidate not in state.by_type.get("ipv4", {}):
            collision = candidate
            break
    assert collision is not None, "expected a Bloom collision in 10K probes"

    # Probe known value first (bloom hit + confirmed match), then collision
    # (bloom hit + false positive). This matches the test's own intent stated
    # in the bloom_hits assertion comment below.
    assert matcher.check("1.2.3.4", "ipv4") is not None
    assert matcher.check(collision, "ipv4") is None
    metrics = matcher.metrics_snapshot()
    assert metrics.false_positives_total == 1
    assert metrics.bloom_hits_total >= 2  # known-value probe + collision probe


def _evt(
    *,
    ips: tuple[str, ...] = (),
    hashes: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    url: str | None = None,
) -> SeerflowEvent:
    attrs: dict[str, str] = {}
    if url is not None:
        attrs["url"] = url
    return SeerflowEvent(
        event_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        timestamp_ns=1,
        observed_ns=1,
        related_ips=ips,
        related_domains=domains,
        related_hashes=hashes,
        attributes=attrs,
    )


@pytest.mark.asyncio
async def test_check_event_extracts_ip_domain_hash_url() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    indicators = (
        _ipv4("1.2.3.4"),
        Indicator(
            value="evil.example",
            type="domain",
            source_feed="f1",
            confidence=80,
            kill_chain_phases=(),
            valid_from_ns=0,
            valid_until_ns=None,
        ),
        Indicator(
            value="aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
            type="sha256",
            source_feed="f1",
            confidence=80,
            kill_chain_phases=(),
            valid_from_ns=0,
            valid_until_ns=None,
        ),
        Indicator(
            value="https://evil.example/x",
            type="url",
            source_feed="f1",
            confidence=80,
            kill_chain_phases=(),
            valid_from_ns=0,
            valid_until_ns=None,
        ),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=indicators,
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    captured: list[IoCMatch] = []
    matcher = IoCMatcher(  # type: ignore[arg-type]
        config=cfg,
        model_store=store,
        on_match=captured.append,
    )
    await matcher.refresh()

    evt = _evt(
        ips=("1.2.3.4",),
        domains=("evil.example",),
        hashes=("sha256:aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",),
        url="https://evil.example/x",
    )
    matches = matcher.check_event(evt)
    assert {m.type for m in matches} == {"ipv4", "domain", "sha256", "url"}
    # on_match dispatch fired for every match.
    assert {m.type for m in captured} == {"ipv4", "domain", "sha256", "url"}


@pytest.mark.asyncio
async def test_check_event_classifies_ipv4_vs_ipv6() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(enabled=True, feeds=feeds, matcher=IoCMatcherConfig(enabled=True))
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            Indicator(
                value="2001:db8::1",
                type="ipv6",
                source_feed="f1",
                confidence=80,
                kill_chain_phases=(),
                valid_from_ns=0,
                valid_until_ns=None,
            ),
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    matches = matcher.check_event(_evt(ips=("2001:db8::1",)))
    assert {m.type for m in matches} == {"ipv6"}


@pytest.mark.asyncio
async def test_check_event_silently_skips_malformed() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(enabled=True, feeds=feeds, matcher=IoCMatcherConfig(enabled=True))
    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    # Garbage IP, hash without prefix, and an unrecognised hash algo prefix —
    # all silently skipped, must not raise.
    evt = _evt(ips=("not-an-ip",), hashes=("noprefix", "blake2b:abcdef"))
    assert matcher.check_event(evt) == ()


@pytest.mark.asyncio
async def test_start_runs_initial_rebuild_and_registers_listener() -> None:
    from seerflow.threat_intel.manager import TAXIIFeedManager

    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    manager = TAXIIFeedManager(config=cfg, model_store=store)  # type: ignore[arg-type]
    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    manager.register_snapshot_listener(matcher.on_snapshot_updated)

    await matcher.start()
    try:
        assert matcher.metrics_snapshot().rebuild_count == 1
        assert matcher.check("1.2.3.4", "ipv4") is not None
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_listener_triggers_debounced_rebuild() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=10),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.start()
    try:
        before = matcher.metrics_snapshot().rebuild_count
        for _ in range(5):
            matcher.on_snapshot_updated("f1")
        await asyncio.sleep(0.1)
        after = matcher.metrics_snapshot().rebuild_count
        assert after == before + 1
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_stop_cancels_loop_and_is_idempotent() -> None:
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    await matcher.start()
    await matcher.stop()
    await matcher.stop()  # second call must be a no-op


@pytest.mark.asyncio
async def test_concurrent_reads_during_rebuild_never_observe_partial_state() -> None:
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()

    stop = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        while not stop.is_set():
            try:
                matcher.check("1.2.3.4", "ipv4")
            except BaseException as exc:  # capture for assert
                errors.append(exc)
                return

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(50):
            await matcher.refresh()
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=1.0)
    assert not errors, f"reader thread observed torn state: {errors}"


def test_check_returns_none_when_state_unbuilt(stub_store: object) -> None:
    """`check()` before any refresh must return None without raising."""
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))
    matcher = IoCMatcher(config=cfg, model_store=stub_store)  # type: ignore[arg-type]
    assert matcher.check("1.2.3.4", "ipv4") is None
    assert matcher.metrics_snapshot().checks_total == 1


@pytest.mark.asyncio
async def test_check_event_skips_unknown_candidates() -> None:
    """Well-formed candidates that aren't in the indicator set must be skipped."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    # Event mixes one matching IP with several well-formed-but-unknown values
    # across every candidate type, exercising the `continue` skip branch.
    evt = _evt(
        ips=("1.2.3.4", "9.9.9.9"),
        domains=("unknown.example",),
        hashes=(
            "md5:11111111111111111111111111111111",
            "sha1:2222222222222222222222222222222222222222",
            "sha256:3333333333333333333333333333333333333333333333333333333333333333",
        ),
        url="https://unknown.example/y",
    )
    matches = matcher.check_event(evt)
    assert {m.value for m in matches} == {"1.2.3.4"}


@pytest.mark.asyncio
async def test_check_event_swallows_on_match_callback_exception() -> None:
    """A raising on_match must not stop further matches or propagate."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    def boom(_m: IoCMatch) -> None:
        raise RuntimeError("listener exploded")

    matcher = IoCMatcher(  # type: ignore[arg-type]
        config=cfg,
        model_store=store,
        on_match=boom,
    )
    await matcher.refresh()
    # Must not raise even though callback does.
    matches = matcher.check_event(_evt(ips=("1.2.3.4",)))
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_start_is_idempotent_while_running() -> None:
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    await matcher.start()
    try:
        first_task = matcher._task
        await matcher.start()  # second call — must short-circuit
        assert matcher._task is first_task
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_start_rejects_during_shutdown() -> None:
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    matcher._stopping = True  # simulate mid-shutdown
    with pytest.raises(RuntimeError, match="mid-shutdown"):
        await matcher.start()


@pytest.mark.asyncio
async def test_run_loop_no_debounce_when_zero_ms() -> None:
    """rebuild_debounce_ms=0 must skip the asyncio.sleep branch."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=0),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.start()
    try:
        before = matcher.metrics_snapshot().rebuild_count
        matcher.on_snapshot_updated("f1")
        await asyncio.sleep(0.05)
        assert matcher.metrics_snapshot().rebuild_count == before + 1
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_run_loop_reruns_when_dirty_set_during_rebuild() -> None:
    """If a notification arrives while refresh() runs, the loop iterates again."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=0),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]

    # Initial refresh BEFORE we install the hook, so start() is clean.
    await matcher.refresh()
    base = matcher.metrics_snapshot().rebuild_count

    original_refresh = matcher.refresh
    notified = {"count": 0}

    async def refresh_then_redirty() -> None:
        await original_refresh()
        # Re-dirty exactly once mid-rebuild to force the `continue` branch.
        if notified["count"] == 0:
            notified["count"] = 1
            assert matcher._dirty_event is not None
            matcher._dirty_event.set()

    matcher.refresh = refresh_then_redirty  # type: ignore[method-assign]

    # Bind the event to the running loop (start() normally does this) and
    # then launch the run loop directly without re-running refresh.
    matcher._dirty_event = asyncio.Event()
    matcher._task = asyncio.create_task(matcher._run_loop(), name="ioc_matcher.loop")
    try:
        # First listener call wakes the loop. During that refresh the hook
        # re-sets the dirty event, hitting the `if dirty_event.is_set():
        # continue` branch and forcing a second rebuild without another
        # listener call.
        matcher.on_snapshot_updated("f1")
        await asyncio.sleep(0.1)
        after = matcher.metrics_snapshot().rebuild_count
        # listener wake (one rebuild) + continue branch (second rebuild) >= 2
        assert after - base >= 2
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_build_state_skips_disabled_feeds() -> None:
    store = _MemStore()
    feeds = (
        TAXIIFeedConfig(id="f1", url="https://x", collection_id="c", enabled=False),
        TAXIIFeedConfig(id="f2", url="https://y", collection_id="d"),
    )
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    # Both feeds have snapshots persisted, but f1 is disabled and must be skipped.
    for fid, val in (("f1", "1.2.3.4"), ("f2", "5.6.7.8")):
        s = IndicatorSnapshot(
            feed_id=fid,
            fetched_at_ns=1,
            indicators=(_ipv4(val, source=fid),),
            cursor=None,
        )
        await store.save_state(f"taxii:snapshot:{fid}", msgspec.msgpack.encode(s))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.check("1.2.3.4", "ipv4") is None  # f1 skipped
    assert matcher.check("5.6.7.8", "ipv4") is not None


@pytest.mark.asyncio
async def test_build_state_warns_when_bit_array_exceeds_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Capacity that pushes byte_size > 10 MB triggers a WARNING but still serves."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    # min_capacity 2_000_000 with fpr=0.001 → ~3.4 MB; force >10 MB by lifting
    # min_capacity past the threshold (≈ 5.8M items @ 0.001 → ≥10 MB).
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True, min_capacity=6_000_000, fpr=0.001),
    )
    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    with caplog.at_level("WARNING", logger="seerflow"):
        await matcher.refresh()
    assert any("exceeds 10 MB target" in rec.message for rec in caplog.records)
    # Matcher still served the rebuild: bit_array_bytes reflects the oversized array.
    assert matcher.metrics_snapshot().bit_array_bytes > 10 * 1024 * 1024


@pytest.mark.asyncio
async def test_restart_after_stop_rebuilds_fresh_bit_array() -> None:
    """AC12: stop() + start() cycles must rebuild the bit array from a fresh snapshot."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap1 = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap1))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.start()
    try:
        assert matcher._state is not None
        prior_id = id(matcher._state.bloom)
        assert matcher.check("1.2.3.4", "ipv4") is not None
    finally:
        await matcher.stop()

    # Replace the snapshot with a different indicator under the same feed id.
    snap2 = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=2,
        indicators=(_ipv4("5.6.7.8"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap2))

    await matcher.start()
    try:
        assert matcher._state is not None
        assert id(matcher._state.bloom) != prior_id
        assert matcher.check("5.6.7.8", "ipv4") is not None
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_refresh_failure_keeps_previous_state_and_increments_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising _build_state must preserve prior state and bump rebuild_failures_total."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    assert matcher.check("1.2.3.4", "ipv4") is not None
    prior_state = matcher._state
    assert prior_state is not None

    async def _boom() -> object:
        raise RuntimeError("simulated rebuild failure")

    monkeypatch.setattr(matcher, "_build_state", _boom)
    await matcher.refresh()

    # State unchanged — same object identity preserved.
    assert matcher._state is prior_state
    metrics = matcher.metrics_snapshot()
    assert metrics.rebuild_failures_total == 1
    assert metrics.rebuild_count == 1  # still just the prior successful refresh
    # Known indicator still matches via preserved state.
    assert matcher.check("1.2.3.4", "ipv4") is not None


@pytest.mark.asyncio
async def test_stop_before_start_does_not_brick_matcher() -> None:
    """stop() before start() must reset _stopping so a later start() is not bricked."""
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    # No start() — task is None. Calling stop() must clear _stopping.
    await matcher.stop()
    assert matcher._stopping is False
    # Subsequent start() must not raise RuntimeError("mid-shutdown").
    await matcher.start()
    try:
        assert matcher.metrics_snapshot().rebuild_count == 1
    finally:
        await matcher.stop()


@pytest.mark.asyncio
async def test_on_snapshot_updated_before_start_is_noop() -> None:
    """A listener firing before start() must drop the signal silently."""
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    # _dirty_event is None pre-start — must not raise.
    matcher.on_snapshot_updated("f1")
    # Pre-start signals are dropped: the dirty event remains unbound and a
    # subsequent start() will refresh() unconditionally.
    assert matcher._dirty_event is None


@pytest.mark.asyncio
async def test_run_loop_raises_when_dirty_event_unbound() -> None:
    """Defensive: ``_run_loop`` must surface a clear error if it is launched
    without ``start()`` having bound the dirty event."""
    cfg = ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True))

    class _Store:
        async def save_state(self, *_a, **_k) -> None:
            return None

        async def load_state(self, *_a, **_k) -> bytes | None:
            return None

        async def delete_state(self, *_a, **_k) -> None:
            return None

    matcher = IoCMatcher(config=cfg, model_store=_Store())  # type: ignore[arg-type]
    assert matcher._dirty_event is None
    with pytest.raises(RuntimeError, match="dirty_event"):
        await matcher._run_loop()


@pytest.mark.asyncio
async def test_ipv6_canonical_form_match() -> None:
    """Indicator stored as ``::1`` matches event entity ``0:0:0:0:0:0:0:1``."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            Indicator(
                value="::1",
                type="ipv6",
                source_feed="f1",
                confidence=80,
                kill_chain_phases=(),
                valid_from_ns=0,
                valid_until_ns=None,
            ),
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    matches = matcher.check_event(_evt(ips=("0:0:0:0:0:0:0:1",)))
    assert {m.type for m in matches} == {"ipv6"}


@pytest.mark.asyncio
async def test_ipv4_already_canonical_no_break() -> None:
    """IPv4 indicators in canonical dotted-decimal still match unchanged."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    matches = matcher.check_event(_evt(ips=("1.2.3.4",)))
    assert {m.value for m in matches} == {"1.2.3.4"}


@pytest.mark.asyncio
async def test_build_state_drops_malformed_ip_indicator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A feed shipping an unparseable IP value is logged and skipped, not crashed."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    bad_ind = Indicator(
        value="not-an-ip",
        type="ipv4",
        source_feed="f1",
        confidence=80,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )
    good_ind = _ipv4("1.2.3.4")
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(bad_ind, good_ind),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    with caplog.at_level("WARNING", logger="seerflow"):
        await matcher.refresh()
    assert any("not a valid IP" in rec.message for rec in caplog.records)
    # Good indicator survives; bad one dropped.
    assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 1}
    assert matcher.check("1.2.3.4", "ipv4") is not None


@pytest.mark.asyncio
async def test_domain_case_normalized_match() -> None:
    """Indicator ``evil.example`` matches event domain ``Evil.Example`` (case-fold)."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            Indicator(
                value="evil.example",
                type="domain",
                source_feed="f1",
                confidence=80,
                kill_chain_phases=(),
                valid_from_ns=0,
                valid_until_ns=None,
            ),
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    matches = matcher.check_event(_evt(domains=("Evil.Example",)))
    assert {m.type for m in matches} == {"domain"}


@pytest.mark.asyncio
async def test_hash_case_normalized_match() -> None:
    """Hash event with uppercase digest + uppercase algo prefix still matches."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    cfg = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(
            Indicator(
                value=digest.upper(),  # feed shipped uppercase
                type="sha256",
                source_feed="f1",
                confidence=80,
                kill_chain_phases=(),
                valid_from_ns=0,
                valid_until_ns=None,
            ),
        ),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))

    matcher = IoCMatcher(config=cfg, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    # Event ships the same digest in mixed case with uppercase algo prefix.
    matches = matcher.check_event(_evt(hashes=(f"SHA256:{digest.upper()}",)))
    assert {m.type for m in matches} == {"sha256"}


@pytest.mark.asyncio
async def test_build_state_refuses_bloom_above_hard_cap() -> None:
    """Bloom byte_size exceeding the 100 MB ceiling must raise + preserve prior state."""
    store = _MemStore()
    feeds = (TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),)
    # Seed a viable prior state first.
    snap = IndicatorSnapshot(
        feed_id="f1",
        fetched_at_ns=1,
        indicators=(_ipv4("1.2.3.4"),),
        cursor=None,
    )
    await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))
    cfg_ok = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(enabled=True),
    )
    matcher = IoCMatcher(config=cfg_ok, model_store=store)  # type: ignore[arg-type]
    await matcher.refresh()
    prior_state = matcher._state
    assert prior_state is not None
    # Now swap in a config with capacity/fpr that pushes byte_size > 100 MB.
    # 200M items @ fpr=1e-6 → ~700 MB which is well above the cap.
    cfg_huge = ThreatIntelConfig(
        enabled=True,
        feeds=feeds,
        matcher=IoCMatcherConfig(
            enabled=True,
            min_capacity=200_000_000,
            fpr=1e-6,
        ),
    )
    matcher._cfg = cfg_huge
    matcher._matcher_cfg = cfg_huge.matcher
    await matcher.refresh()
    # State unchanged + failure counter bumped.
    assert matcher._state is prior_state
    assert matcher.metrics_snapshot().rebuild_failures_total == 1
