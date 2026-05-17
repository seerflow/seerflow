"""Coverage for ``pipeline.handler._feed_kill_chain`` (S-236).

Targets handler.py lines 127-143: the kill-chain tracker None early-return,
the per-kc-alert write + sink fan-out (is_new True/False) and the
``except Exception`` swallow.

``_feed_kill_chain`` is an inner closure, so it is exercised through the
public handler: an ML anomaly produces an alert whose write triggers
``await _feed_kill_chain(alert)``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.unit.alert_factory import make_alert

from .conftest import HandlerTestHarness, make_detection_result, make_raw_event

_ANOMALY = make_detection_result(score=0.95, is_anomaly=True, anomaly_direction="upper")


async def test_kill_chain_none_is_noop(harness: HandlerTestHarness) -> None:
    """No kill_chain_tracker → handler still processes the anomaly cleanly."""
    handler = harness.build(ensemble=harness.ensemble)
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)

    await handler(make_raw_event())

    harness.storage.write_alert.assert_awaited()


async def test_kill_chain_alert_fans_out_when_new(harness: HandlerTestHarness) -> None:
    """record_alert yields a kc alert; is_new=True → all sinks enqueue it."""
    kc_alert = make_alert(rule_name="kc-progression", alert_type="kill_chain")
    tracker = MagicMock()
    tracker.record_alert = MagicMock(return_value=[kc_alert])
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)

    handler = harness.build(kill_chain_tracker=tracker)
    await handler(make_raw_event())

    tracker.record_alert.assert_called()
    harness.assert_fanned_out(kc_alert)


async def test_kill_chain_alert_not_fanned_out_when_deduped(
    harness: HandlerTestHarness,
) -> None:
    """is_new=False (dedup hit) → kc alert is not enqueued anywhere."""
    kc_alert = make_alert(rule_name="kc-progression", alert_type="kill_chain")
    tracker = MagicMock()
    tracker.record_alert = MagicMock(return_value=[kc_alert])
    harness.storage.write_alert.return_value = False
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)

    handler = harness.build(kill_chain_tracker=tracker)
    await handler(make_raw_event())

    harness.dispatcher.enqueue.assert_not_called()
    harness.pagerduty.enqueue_trigger.assert_not_called()
    harness.otlp.enqueue.assert_not_called()


async def test_kill_chain_write_exception_is_swallowed(
    harness: HandlerTestHarness,
) -> None:
    """write_alert raising inside _feed_kill_chain must not propagate."""
    kc_alert = make_alert(rule_name="kc-progression", alert_type="kill_chain")
    tracker = MagicMock()
    tracker.record_alert = MagicMock(return_value=[kc_alert])
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)

    call_count = {"n": 0}

    async def _flaky_write(alert: object, **_kw: object) -> bool:
        # First call = the ML alert itself (succeeds, triggers _feed_kill_chain);
        # the kc-alert write then raises and must be swallowed.
        call_count["n"] += 1
        if getattr(alert, "rule_name", "") == "kc-progression":
            raise RuntimeError("boom")
        return True

    harness.storage.write_alert.side_effect = _flaky_write

    handler = harness.build(kill_chain_tracker=tracker)
    await handler(make_raw_event())  # must not raise

    assert call_count["n"] >= 2
