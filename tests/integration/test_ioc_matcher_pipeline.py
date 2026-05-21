"""End-to-end: IoCMatcher refresh against the real SQLite ModelStore."""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

import msgspec
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from seerflow.config import (
    IoCMatcherConfig,
    StorageConfig,
    TAXIIFeedConfig,
    ThreatIntelConfig,
)
from seerflow.models.indicator import Indicator, IndicatorSnapshot
from seerflow.storage.factory import connect_storage
from seerflow.threat_intel.matcher import IoCMatcher


def _ipv4(value: str) -> Indicator:
    return Indicator(
        value=value,
        type="ipv4",
        source_feed="f1",
        confidence=80,
        kill_chain_phases=(),
        valid_from_ns=0,
        valid_until_ns=None,
    )


# coverage.py installs a global trace function that ~2x's wall-clock time.
# AC2 is a developer-laptop benchmark — measure it without trace overhead so
# the gate doesn't shift just because we're collecting coverage.
_UNDER_COVERAGE = sys.gettrace() is not None

# S-237 (SEE-261): the 100K-indicator rebuild (msgpack decode + Bloom filter +
# confirmation dict) is genuinely CPU-bound — its wall clock scales with the
# CPU it actually gets. A fixed ceiling flakes under full-suite parallel load
# on a saturated host even though the rebuild is correct. When the 1-minute
# load average per available CPU reaches this threshold the host is
# meaningfully oversubscribed and a single-shot wall-clock benchmark carries
# no signal about the code, so the timing ceiling (and only the timing
# ceiling) is skipped — the functional assertions stay unconditional. At 1.0
# the run queue merely equals CPU count (fully busy, not necessarily
# starved); 1.5 means demonstrable oversubscription. This mirrors the spirit
# of the coverage-aware branch above (disable a measurement the environment
# has rendered uninformative) rather than inventing a flaky fudge factor.
_SATURATION_LOAD_PER_CPU = 1.5


def _current_load1() -> float | None:
    """1-minute system load average, or ``None`` where unavailable.

    ``os.getloadavg()`` raises ``OSError`` on platforms that do not expose a
    load average (e.g. some non-Linux CI). Treat that as "load unknown" so
    the caller falls back to the strict budget — behaviour is unchanged
    wherever the call is unavailable.
    """
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def _available_cpus() -> int:
    """CPUs actually schedulable by this process (cgroup/affinity aware)."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def _rebuild_timing_decision(
    load1: float | None,
    cpu_count: int,
    under_coverage: bool,
) -> tuple[bool, float, str]:
    """Decide whether to assert the rebuild timing ceiling, and which budget.

    Returns ``(should_assert, budget_s, reason)``:

    * ``should_assert`` — ``False`` means the host is demonstrably saturated
      and the wall-clock measurement is uninformative, so the caller must
      *skip* the timing ceiling (the functional assertions still run
      unconditionally). ``True`` means assert ``elapsed < budget_s``.
    * ``budget_s`` — the strict ceiling: 3.0 s under coverage tracing
      (mirrors the existing ``sys.gettrace()`` cushion), else 1.0 s.
    * ``reason`` — human-readable explanation for the skip/assert message.

    ``cpu_count`` is clamped to a minimum of 1 (a non-positive value would
    otherwise divide by zero and, treated as 1, biases toward *skip* — never
    toward a false failure).
    """
    budget_s = 3.0 if under_coverage else 1.0
    if load1 is None:
        return True, budget_s, "load unknown — strict budget"
    cpu = max(1, cpu_count)
    load_per_cpu = load1 / cpu
    if load_per_cpu >= _SATURATION_LOAD_PER_CPU:
        return (
            False,
            budget_s,
            f"host saturated (load/cpu={load_per_cpu:.2f} "
            f">= {_SATURATION_LOAD_PER_CPU}) — timing ceiling skipped",
        )
    return (
        True,
        budget_s,
        f"host not saturated (load/cpu={load_per_cpu:.2f}) — strict budget",
    )


async def test_matcher_rebuilds_within_one_second_for_100k_indicators(
    tmp_path: Path,
) -> None:
    store = await connect_storage(StorageConfig(data_dir=str(tmp_path)))
    try:
        snap = IndicatorSnapshot(
            feed_id="f1",
            fetched_at_ns=1,
            indicators=tuple(
                # 100K distinct, valid IPv4s — span 10.0.0.0/14 (256x256x4=262K)
                # so every octet stays inside [0, 255].
                _ipv4(f"10.{i // 65_536}.{(i // 256) % 256}.{i % 256}")
                for i in range(100_000)
            ),
            cursor=None,
        )
        await store.save_state("taxii:snapshot:f1", msgspec.msgpack.encode(snap))
        cfg = ThreatIntelConfig(
            enabled=True,
            feeds=(TAXIIFeedConfig(id="f1", url="https://x", collection_id="c"),),
            matcher=IoCMatcherConfig(enabled=True, rebuild_debounce_ms=10),
        )
        matcher = IoCMatcher(config=cfg, model_store=store)
        t0 = time.monotonic()
        await matcher.refresh()
        elapsed = time.monotonic() - t0

        # Functional correctness is asserted UNCONDITIONALLY and before any
        # timing decision — these never get skipped regardless of host load.
        assert matcher.metrics_snapshot().indicators_loaded == {"ipv4": 100_000}
        assert matcher.check("10.0.0.0", "ipv4") is not None

        # The timing ceiling is the only host-load-sensitive part. On an
        # unloaded host the strict ~1 s benchmark is enforced (a real
        # regression still fails); under demonstrable CPU saturation the
        # single-shot wall clock is uninformative, so skip only the ceiling.
        should_assert, budget_s, reason = _rebuild_timing_decision(
            _current_load1(), _available_cpus(), _UNDER_COVERAGE
        )
        if not should_assert:
            pytest.skip(reason)
        assert elapsed < budget_s, (
            f"refresh took {elapsed:.2f}s, must be < {budget_s}s "
            f"(under_coverage={_UNDER_COVERAGE}, {reason})"
        )
    finally:
        await store.close()
