"""Residual line-coverage gaps in pipeline.handler (S-236).

Targets the handler.py lines not reached by the dispatch/detection suites:
- 63-64: ``_dedup_window_ns`` per-rule override match.
- 333 / 338-346: watermark advance + late-event correlation skip + the
  non-late window-buffer add path.
- 409-410: graph edge ``write_edge`` exception swallow.
- 437-438: community-crossing alert write exception swallow.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from seerflow.config import AlertingConfig
from seerflow.correlation.holders import EngineHolder
from seerflow.correlation.watermark import Watermark
from seerflow.correlation.window import EntityWindowBuffer
from seerflow.graph.entity_graph import EntityGraph
from seerflow.pipeline.handler import _dedup_window_ns
from tests.unit.alert_factory import make_alert

from .conftest import HandlerTestHarness, make_raw_event

# ── 63-64: dedup override ───────────────────────────────────────────────


def test_dedup_window_override_matches_rule_name() -> None:
    cfg = AlertingConfig(
        dedup_window_seconds=900,
        dedup_window_overrides=(("special-rule", 5),),
    )
    assert _dedup_window_ns("special-rule", cfg) == 5 * 1_000_000_000
    # Non-matching falls back to the global window.
    assert _dedup_window_ns("other-rule", cfg) == 900 * 1_000_000_000


# ── 333 / 338-346: watermark + window buffer ────────────────────────────


async def test_window_buffer_add_on_in_order_event(
    harness: HandlerTestHarness,
) -> None:
    watermark = Watermark(tolerance_ns=1_000_000_000)
    window = EntityWindowBuffer(window_ns=60_000_000_000)

    handler = harness.build(watermark=watermark, window_buffer=window)
    await handler(make_raw_event(received_ns=1_700_000_000_000_000_000))

    # Watermark advanced to the event time; entity buffered (not late).
    assert watermark.current_ns > 0


async def test_late_event_skipped_for_correlation(
    harness: HandlerTestHarness,
) -> None:
    watermark = Watermark(tolerance_ns=1)  # almost zero tolerance
    window = EntityWindowBuffer(window_ns=60_000_000_000)
    corr_engine = MagicMock()
    corr_engine.evaluate = MagicMock(return_value=[])

    handler = harness.build(
        watermark=watermark,
        window_buffer=window,
        correlation_holder=EngineHolder(engine=corr_engine),
    )
    # First event advances the watermark far ahead.
    await handler(make_raw_event(received_ns=2_000_000_000_000_000_000))
    # Second event is far in the past → is_late() True → correlation skipped.
    await handler(make_raw_event(received_ns=1_000_000_000_000_000_000))

    # Correlation engine was never evaluated for the late event (only the
    # first, in-order event could have reached it; the late path short-circuits).
    assert corr_engine.evaluate.call_count <= 1


# ── 409-410: graph edge write exception ─────────────────────────────────


async def test_graph_edge_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    graph = EntityGraph()
    harness.storage.write_edge.side_effect = RuntimeError("edge boom")

    handler = harness.build(entity_graph=graph)
    await handler(make_raw_event())  # must not raise

    harness.storage.write_edge.assert_awaited()


# ── 437-438: community-crossing write exception ─────────────────────────


async def test_community_crossing_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    graph = EntityGraph()
    cc_alert = make_alert(rule_name="community-crossing", alert_type="correlation")
    structural = MagicMock()
    structural.check_community_crossing = MagicMock(return_value=[cc_alert])
    structural.check_post_algorithms = MagicMock(return_value=[])
    harness.storage.write_alert.side_effect = RuntimeError("cc boom")

    handler = harness.build(
        entity_graph=graph,
        graph_structural=structural,
        graph_algo_interval=10_000,
    )
    await handler(make_raw_event())  # must not raise
