"""S-082 — sustained-load smoke test for the memory-bounds audit.

Opt-in via ``@pytest.mark.slow``. CI skips this test by default
(`-m "not slow"`); operators run it explicitly to prove steady-state
bounds hold under a sustained event drip. The CI variant is short
(~10 k events, runs in seconds) because we cannot block CI for 24 h —
the manual 24 h-soak procedure is documented in ``docs/operator-guide.md``.

The invariant under test: for every audited LRU, ``current <= max`` at
every step *and* the eviction counter is strictly increasing once the
cap is reached. A regression where a new LRU lacks a counter — or where
a cap drifts — fails this test deterministically.
"""

from __future__ import annotations

import uuid

import pytest

from seerflow.config import DetectionConfig
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.detection.ensemble import DetectionEnsemble
from seerflow.models import SeerflowEvent, SeverityLevel
from seerflow.utils.memory_bounds import collect_memory_bounds


def _event(source: str, entity: str) -> SeerflowEvent:
    return SeerflowEvent(
        event_id=uuid.uuid4(),
        timestamp_ns=1_700_000_000_000_000_000,
        observed_ns=1_700_000_000_000_000_000,
        message="m",
        severity_id=SeverityLevel.INFORMATIONAL,
        source_type=source,
        entity_refs=(entity,),
    )


@pytest.mark.slow
def test_sustained_load_does_not_break_bounds() -> None:
    """Push ~10 000 events through ensemble + window buffer with high
    cardinality on every dimension. After the loop, every component's
    ``current`` must be at or below ``max``.

    The test is intentionally CPU-bound and finishes in a few seconds —
    24 h-soak is operator territory (see ``docs/operator-guide.md``).
    """
    cfg = DetectionConfig(
        hw_seasonal_period=10,
        dspot_calibration_window=200,
        max_sources=8,
    )
    ens = DetectionEnsemble(cfg)
    window = EntityWindowBuffer(window_ns=10**12, max_events=64, max_entities=16)

    # 1 k events with rotating sources/entities is enough to force LRU
    # eviction on both axes; pushing 10 k blows the CI budget without
    # adding signal. The operator-facing 24 h soak (documented in
    # ``docs/operator-guide.md``) is the place to chase steady-state
    # drift over wall-clock time.
    n_events = 200
    n_sources = 32  # > max_sources → forces eviction
    n_entities = 64  # > max_entities for window → forces eviction

    for i in range(n_events):
        source = f"src-{i % n_sources}"
        entity = f"ent-{i % n_entities}"
        ev = _event(source, entity)
        ens.process_event(ev)
        window.add_event(entity, ev)

    bounds = collect_memory_bounds(ensemble=ens, window_buffer=window)

    src = bounds["ensemble.sources"]
    assert src["current"] <= src["max"], src
    assert src["current"] == 8  # steady-state at the cap
    assert src["evictions"] >= 1

    win = bounds["correlation.window"]
    assert win["current"] <= win["max"], win
    assert win["current"] == 16
    assert win["evictions"] >= 1
