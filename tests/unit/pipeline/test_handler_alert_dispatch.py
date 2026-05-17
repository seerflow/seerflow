"""Coverage for UEBA / IoC / correlation alert-dispatch branches (S-236).

Targets handler.py clusters:
- UEBA scoring + alert dispatch + write-exception (253-260).
- IoC enrichment dispatch: select_entity_uuid empty → counter (274-275),
  fan-out (291-297), risk-register feed (316-317), write-exception.
- Correlation engine alerts: fan-out + per-alert exception + risk feed +
  outer evaluate() exception (333-387).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from seerflow.threat_intel.enricher import _IoCEnrichmentCounters
from seerflow.ueba.engine import UEBAScoreBreakdown
from tests.unit.alert_factory import make_alert
from tests.unit.pipeline.test_handler_ioc import _FakeMatcher, _seed_match

from .conftest import HandlerTestHarness, make_raw_event

# The seed IoC match is keyed on 1.2.3.4 — the event message must carry that
# IP so entity resolution produces a uid select_entity_uuid can bind to.
_IOC_EVENT = make_raw_event(b"probe from 1.2.3.4 for user bob")


def _breakdown(composite: float) -> UEBAScoreBreakdown:
    return UEBAScoreBreakdown(
        time_of_day=0.0,
        source_novelty=0.0,
        volume=0.0,
        pattern_novelty=0.0,
        composite=composite,
    )


# ── UEBA ────────────────────────────────────────────────────────────────


async def test_ueba_alert_fans_out_and_bumps_risk_score(
    harness: HandlerTestHarness,
) -> None:
    ueba_alert = make_alert(rule_name="ueba.deviation", alert_type="ueba")
    ueba_engine = MagicMock()
    ueba_engine.score_and_maybe_alert = MagicMock(return_value=(_breakdown(0.9), ueba_alert))
    baseline_store = MagicMock()
    baseline_store.snapshot_and_learn = MagicMock(return_value=None)

    handler = harness.build(ueba_engine=ueba_engine, baseline_store=baseline_store)
    await handler(make_raw_event())

    ueba_engine.score_and_maybe_alert.assert_called_once()
    harness.assert_fanned_out(ueba_alert)


async def test_ueba_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    ueba_alert = make_alert(rule_name="ueba.deviation", alert_type="ueba")
    ueba_engine = MagicMock()
    ueba_engine.score_and_maybe_alert = MagicMock(return_value=(_breakdown(0.9), ueba_alert))
    baseline_store = MagicMock()
    baseline_store.snapshot_and_learn = MagicMock(return_value=None)
    harness.storage.write_alert.side_effect = RuntimeError("ueba boom")

    handler = harness.build(ueba_engine=ueba_engine, baseline_store=baseline_store)
    await handler(make_raw_event())  # must not raise


async def test_ueba_no_alert_when_engine_returns_none(
    harness: HandlerTestHarness,
) -> None:
    ueba_engine = MagicMock()
    ueba_engine.score_and_maybe_alert = MagicMock(return_value=(_breakdown(0.0), None))
    baseline_store = MagicMock()
    baseline_store.snapshot_and_learn = MagicMock(return_value=None)

    handler = harness.build(ueba_engine=ueba_engine, baseline_store=baseline_store)
    await handler(make_raw_event())

    harness.dispatcher.enqueue.assert_not_called()


# ── IoC ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_ioc_select_entity_uuid_empty_increments_dropped_counter(
    harness: HandlerTestHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters = _IoCEnrichmentCounters()
    builder = MagicMock()
    builder.select_entity_uuid = MagicMock(return_value=("", "", ""))
    builder.enriched_attributes = MagicMock(return_value={})

    # make_handler imports IoCAlertBuilder from threat_intel.enricher at call
    # time — patch it there so the closure uses our stub builder.
    monkeypatch.setattr(
        "seerflow.threat_intel.enricher.IoCAlertBuilder",
        MagicMock(return_value=builder),
    )
    handler = harness.build(
        ioc_matcher=_FakeMatcher(matches=(_seed_match(),)),
        ioc_enrichment_counters=counters,
    )
    await handler(_IOC_EVENT)

    assert counters.dropped_entity_uuid_lookups_total >= 1


async def test_ioc_alert_fans_out_and_feeds_risk(
    harness: HandlerTestHarness,
) -> None:
    counters = _IoCEnrichmentCounters()
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=False)
    risk_register.get_risk = MagicMock(return_value=0.0)

    handler = harness.build(
        ioc_matcher=_FakeMatcher(matches=(_seed_match(),)),
        ioc_enrichment_counters=counters,
        risk_register=risk_register,
    )
    await handler(_IOC_EVENT)

    assert counters.alerts_emitted_total == 1
    assert counters.risk_register_updates_total == 1
    risk_register.add_risk.assert_called()


async def test_ioc_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    counters = _IoCEnrichmentCounters()
    harness.storage.write_alert.side_effect = RuntimeError("ioc boom")

    handler = harness.build(
        ioc_matcher=_FakeMatcher(matches=(_seed_match(),)),
        ioc_enrichment_counters=counters,
    )
    await handler(_IOC_EVENT)  # must not raise


# ── Correlation ─────────────────────────────────────────────────────────


def _holder(engine: object) -> object:
    from seerflow.correlation.holders import EngineHolder

    return EngineHolder(engine=engine)


async def test_correlation_alerts_fan_out_and_feed_risk(
    harness: HandlerTestHarness,
) -> None:
    corr_alert = make_alert(rule_name="corr-rule", alert_type="correlation")
    engine = MagicMock()
    engine.evaluate = MagicMock(return_value=[corr_alert])
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=False)
    risk_register.get_risk = MagicMock(return_value=0.0)

    handler = harness.build(
        correlation_holder=_holder(engine),
        risk_register=risk_register,
    )
    await handler(make_raw_event())

    engine.evaluate.assert_called_once()
    harness.assert_fanned_out(corr_alert)
    risk_register.add_risk.assert_called()


async def test_correlation_per_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    corr_alert = make_alert(rule_name="corr-rule", alert_type="correlation")
    engine = MagicMock()
    engine.evaluate = MagicMock(return_value=[corr_alert])
    harness.storage.write_alert.side_effect = RuntimeError("corr boom")

    handler = harness.build(correlation_holder=_holder(engine))
    await handler(make_raw_event())  # must not raise


async def test_correlation_evaluate_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    engine = MagicMock()
    engine.evaluate = MagicMock(side_effect=RuntimeError("evaluate boom"))

    handler = harness.build(correlation_holder=_holder(engine))
    await handler(make_raw_event())  # must not raise

    engine.evaluate.assert_called_once()
