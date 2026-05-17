"""Coverage for Sigma / graph-structural / risk / periodic-save paths (S-236).

Targets handler.py clusters:
- ML anomaly → create_ml_alerts fan-out + ML risk feed (519-600).
- Sigma fan-out + per-match risk + evaluate() exception (603-641).
- Risk-accumulation alert: threshold crossed, cooldown set, write raise
  (644-688).
- Periodic model save gate (691-702) — time.time_ns patched.
- Graph-algorithm interval block + post-algo structural alerts (704-741).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from seerflow.correlation.holders import EngineHolder
from seerflow.graph.entity_graph import EntityGraph
from tests.unit.alert_factory import make_alert

from .conftest import HandlerTestHarness, make_detection_result, make_raw_event

_ANOMALY = make_detection_result(score=0.95, is_anomaly=True, anomaly_direction="upper")


# ── ML anomaly fan-out + risk ───────────────────────────────────────────


async def test_anomaly_creates_ml_alerts_and_feeds_risk(
    harness: HandlerTestHarness,
) -> None:
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=False)
    risk_register.get_risk = MagicMock(return_value=0.0)
    attack_mapper = MagicMock()
    attack_mapper.lookup = MagicMock(return_value=(("TA0001",), ("T1078",)))

    handler = harness.build(risk_register=risk_register, attack_mapper=attack_mapper)
    await handler(make_raw_event())

    harness.storage.write_alert.assert_awaited()
    risk_register.add_risk.assert_called()


async def test_anomaly_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    harness.ensemble.process_event = MagicMock(return_value=_ANOMALY)
    harness.storage.write_alert.side_effect = RuntimeError("ml boom")

    handler = harness.build()
    await handler(make_raw_event())  # must not raise

    # The except branch was actually entered (write_alert was reached + raised).
    harness.storage.write_alert.assert_awaited()


# ── Sigma ───────────────────────────────────────────────────────────────


async def test_sigma_alerts_fan_out_and_feed_risk(
    harness: HandlerTestHarness,
) -> None:
    sigma_alert = make_alert(rule_name="sigma-rule", alert_type="sigma")
    sigma_engine = MagicMock()
    sigma_engine.evaluate = MagicMock(return_value=[sigma_alert])
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=False)
    risk_register.get_risk = MagicMock(return_value=0.0)

    handler = harness.build(
        sigma_holder=EngineHolder(engine=sigma_engine),
        risk_register=risk_register,
    )
    await handler(make_raw_event())

    sigma_engine.evaluate.assert_called_once()
    harness.assert_fanned_out(sigma_alert)
    risk_register.add_risk.assert_called()


async def test_sigma_evaluate_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    sigma_engine = MagicMock()
    sigma_engine.evaluate = MagicMock(side_effect=RuntimeError("sigma boom"))

    handler = harness.build(sigma_holder=EngineHolder(engine=sigma_engine))
    await handler(make_raw_event())  # must not raise

    sigma_engine.evaluate.assert_called_once()  # outer except actually hit


async def test_sigma_per_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    sigma_alert = make_alert(rule_name="sigma-rule", alert_type="sigma")
    sigma_engine = MagicMock()
    sigma_engine.evaluate = MagicMock(return_value=[sigma_alert])
    harness.storage.write_alert.side_effect = RuntimeError("sigma write boom")

    handler = harness.build(sigma_holder=EngineHolder(engine=sigma_engine))
    await handler(make_raw_event())  # must not raise

    harness.storage.write_alert.assert_awaited()  # per-alert except hit


# ── Risk-accumulation alert ─────────────────────────────────────────────


async def test_risk_threshold_crossed_emits_risk_alert(
    harness: HandlerTestHarness,
) -> None:
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=True)
    risk_register.get_risk = MagicMock(return_value=87.5)

    handler = harness.build(risk_register=risk_register)
    await handler(make_raw_event())

    risk_alerts = [
        c.args[0]
        for c in harness.storage.write_alert.await_args_list
        if getattr(c.args[0], "rule_name", "") == "risk-accumulation"
    ]
    assert risk_alerts, "expected a risk-accumulation alert"
    harness.assert_fanned_out(risk_alerts[0])


async def test_risk_alert_only_once_per_entity(
    harness: HandlerTestHarness,
) -> None:
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=True)
    risk_register.get_risk = MagicMock(return_value=99.0)

    handler = harness.build(risk_register=risk_register)
    await handler(make_raw_event())
    first = harness.storage.write_alert.await_count
    await handler(make_raw_event())  # same entity → risk_alerted skips it

    risk_alerts = [
        c.args[0]
        for c in harness.storage.write_alert.await_args_list
        if getattr(c.args[0], "rule_name", "") == "risk-accumulation"
    ]
    # Exactly one risk-accumulation alert despite two events for same entity.
    assert len({a.entity_uuid for a in risk_alerts}) == len(risk_alerts)
    assert first > 0


async def test_risk_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    risk_register = MagicMock()
    risk_register.check_threshold = MagicMock(return_value=True)
    risk_register.get_risk = MagicMock(return_value=50.0)
    harness.storage.write_alert.side_effect = RuntimeError("risk boom")

    handler = harness.build(risk_register=risk_register)
    await handler(make_raw_event())  # must not raise

    risk_register.check_threshold.assert_called()  # risk block reached
    harness.storage.write_alert.assert_awaited()  # risk alert write attempted


# ── Periodic model save ─────────────────────────────────────────────────


@pytest.mark.unit
async def test_periodic_model_save_fires_on_interval(
    harness: HandlerTestHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Drive 100 events so ``event_count % 100 == 0``; advance time well past
    # the save interval so the inner gate passes.
    clock = {"ns": 0}
    real_handler_mod = __import__("seerflow.pipeline.handler", fromlist=["time"])

    def _fake_time_ns() -> int:
        clock["ns"] += 10_000_000_000_000  # +10000s each read
        return clock["ns"]

    monkeypatch.setattr(real_handler_mod.time, "time_ns", _fake_time_ns)
    harness.ensemble.save_all_state = MagicMock()

    async def _save(_storage: object) -> int:
        return 3

    harness.ensemble.save_all_state.side_effect = _save

    handler = harness.build()
    for _ in range(100):
        await handler(make_raw_event())

    harness.ensemble.save_all_state.assert_called()


async def test_periodic_model_save_exception_swallowed(
    harness: HandlerTestHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"ns": 0}
    real_handler_mod = __import__("seerflow.pipeline.handler", fromlist=["time"])

    def _fake_time_ns() -> int:
        clock["ns"] += 10_000_000_000_000
        return clock["ns"]

    monkeypatch.setattr(real_handler_mod.time, "time_ns", _fake_time_ns)
    harness.ensemble.save_all_state = MagicMock(side_effect=RuntimeError("save boom"))

    handler = harness.build()
    for _ in range(100):
        await handler(make_raw_event())  # must not raise

    harness.ensemble.save_all_state.assert_called()  # save attempted + raised


# ── Graph-algorithm interval + post-algo structural alerts ──────────────


async def test_graph_algorithms_run_on_interval_and_post_alerts_fan_out(
    harness: HandlerTestHarness,
) -> None:
    graph = EntityGraph()
    post_alert = make_alert(rule_name="graph-betweenness", alert_type="correlation")
    structural = MagicMock()
    structural.check_community_crossing = MagicMock(return_value=[])
    structural.check_post_algorithms = MagicMock(return_value=[post_alert])

    handler = harness.build(
        entity_graph=graph,
        graph_structural=structural,
        graph_algo_interval=1,  # run algorithms every event
    )
    # First event adds edges (ip<->user) so vertex_count > 0; algo runs.
    await handler(make_raw_event())
    await handler(make_raw_event())

    structural.check_post_algorithms.assert_called()
    harness.assert_fanned_out(post_alert)


async def test_graph_algorithm_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    # EntityGraph.run_algorithms is slotted (read-only) so use a stub graph
    # that reports a non-empty vertex_count and raises inside run_algorithms.
    graph = MagicMock()
    graph.vertex_count = 5
    graph.edge_count = 4
    graph.add_edge = MagicMock()
    graph.run_algorithms = MagicMock(side_effect=RuntimeError("algo boom"))
    structural = MagicMock()
    structural.check_community_crossing = MagicMock(return_value=[])

    handler = harness.build(
        entity_graph=graph,
        graph_structural=structural,
        graph_algo_interval=1,
    )
    await handler(make_raw_event())
    await handler(make_raw_event())  # must not raise

    graph.run_algorithms.assert_called()


async def test_graph_structural_post_alert_write_exception_swallowed(
    harness: HandlerTestHarness,
) -> None:
    graph = EntityGraph()
    post_alert = make_alert(rule_name="graph-betweenness", alert_type="correlation")
    structural = MagicMock()
    structural.check_community_crossing = MagicMock(return_value=[])
    structural.check_post_algorithms = MagicMock(return_value=[post_alert])
    harness.storage.write_alert.side_effect = RuntimeError("post boom")

    handler = harness.build(
        entity_graph=graph,
        graph_structural=structural,
        graph_algo_interval=1,
    )
    await handler(make_raw_event())
    await handler(make_raw_event())  # must not raise

    structural.check_post_algorithms.assert_called()  # post-algo path reached
    harness.storage.write_alert.assert_awaited()  # alert write attempted + raised


async def test_community_crossing_alerts_fan_out(
    harness: HandlerTestHarness,
) -> None:
    graph = EntityGraph()
    cc_alert = make_alert(rule_name="community-crossing", alert_type="correlation")
    structural = MagicMock()
    structural.check_community_crossing = MagicMock(return_value=[cc_alert])
    structural.check_post_algorithms = MagicMock(return_value=[])

    handler = harness.build(
        entity_graph=graph,
        graph_structural=structural,
        graph_algo_interval=10_000,  # don't run algorithms; only edge-crossing
    )
    await handler(make_raw_event())

    harness.assert_fanned_out(cc_alert)
