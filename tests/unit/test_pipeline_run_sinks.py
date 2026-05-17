"""Deterministic full-``_run_with_config`` drive for sink wiring (S-236).

Targets the ``run.py`` clusters that live inside the ~600-line
``_run_with_config`` orchestrator and are otherwise only reachable in
production:

- 804-852: AlertDispatcher / webhook-session construction + dispatcher task.
- 854-869: PagerDuty + OTLP sink construction + their run() tasks.
- 920-1015: sibling-task wait, reloader cancel, bounded drain, and the big
  ``finally`` teardown that stops every sink/session and closes storage.

Everything is mocked — no real uvicorn, no real network, no real storage.
``asyncio.create_task`` still runs (real loop) but every target's ``run()``
is an AsyncMock that returns immediately, and ``uvicorn.Server`` is a stub
whose ``serve()`` returns at once so the sibling wait completes deterministically.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import AlertingConfig, SeerflowConfig, StorageConfig
from seerflow.pipeline.run import _run_with_config


class _FakePipeline:
    """Pipeline stub whose run() returns immediately and stop() is a noop."""

    def __init__(self) -> None:
        self.manager = MagicMock()
        self.manager._receivers = {}
        self.stopped = False

    async def run(self, _handler: Any) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True


class _FakeServer:
    """uvicorn.Server stand-in — serve() returns at once; flags settable."""

    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.should_exit = False
        self.force_exit = False
        self.started = True
        self.capture_signals = MagicMock()

    async def serve(self) -> None:
        return None


def _fake_app() -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    app.state.ws_manager = MagicMock()
    return app


def _patch_sink(monkeypatch: pytest.MonkeyPatch, dotted: str) -> MagicMock:
    """Patch a sink/dispatcher class so its instance.run()/stop() are noops."""
    inst = MagicMock()
    inst.run = AsyncMock()
    inst.stop = AsyncMock()
    inst.close = AsyncMock()
    inst.enqueue = MagicMock()
    inst.enqueue_trigger = MagicMock()
    monkeypatch.setattr(dotted, MagicMock(return_value=inst))
    return inst


async def _drive(monkeypatch: pytest.MonkeyPatch, alerting: AlertingConfig) -> dict[str, Any]:
    """Run ``_run_with_config`` to completion with everything stubbed."""
    import seerflow.pipeline.run as run_mod

    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    monkeypatch.setattr(run_mod, "connect_storage", AsyncMock(return_value=storage))

    fake_pipeline = _FakePipeline()
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=fake_pipeline))
    monkeypatch.setattr(run_mod.uvicorn, "Server", _FakeServer)

    # Threat-intel + ensemble are heavy; stub their lifecycles.
    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    monkeypatch.setattr(run_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(return_value=0)
    ensemble.save_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(run_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))
    monkeypatch.setattr(run_mod, "make_handler", MagicMock(return_value=MagicMock()))

    disp = _patch_sink(monkeypatch, "seerflow.alerting.dispatcher.AlertDispatcher")
    monkeypatch.setattr(
        "seerflow.alerting.dispatcher.build_webhook_delivery_targets",
        MagicMock(return_value=[]),
    )
    pd = _patch_sink(monkeypatch, "seerflow.alerting.sinks.pagerduty.PagerDutySink")
    otlp = _patch_sink(monkeypatch, "seerflow.alerting.sinks.otlp.OtlpSink")

    # Avoid opening real aiohttp sockets.
    sess = MagicMock()
    sess.close = AsyncMock()
    monkeypatch.setattr(run_mod.aiohttp, "ClientSession", MagicMock(return_value=sess))
    monkeypatch.setattr(run_mod.aiohttp, "TCPConnector", MagicMock(return_value=MagicMock()))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=alerting,
        shutdown_timeout_s=1.0,
    )

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    return {
        "storage": storage,
        "pipeline": fake_pipeline,
        "dispatcher": disp,
        "pagerduty": pd,
        "otlp": otlp,
        "session": sess,
    }


@pytest.mark.unit
async def test_run_with_all_sinks_configured_constructs_and_tears_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """webhook + PagerDuty + OTLP all configured → constructed then stopped."""
    from seerflow.alerting.dispatcher import WebhookTarget

    alerting = AlertingConfig(
        webhook_targets=(WebhookTarget(name="wh", url="https://x.example", format="json"),),
        pagerduty_routing_key="pd-key-123",
        otlp_endpoint="http://collector:4317",
        otlp_protocol="grpc",
    )
    out = await _drive(monkeypatch, alerting)

    # Dispatcher + both sinks were constructed and their run() scheduled.
    out["dispatcher"].run.assert_awaited()
    out["pagerduty"].run.assert_awaited()
    out["otlp"].run.assert_awaited()
    # Finally-block teardown ran for every resource.
    out["dispatcher"].stop.assert_awaited()
    out["pagerduty"].stop.assert_awaited()
    out["otlp"].stop.assert_awaited()
    out["otlp"].close.assert_awaited()
    out["storage"].close.assert_awaited()


@pytest.mark.unit
async def test_run_with_no_optional_sinks_still_tears_down_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No webhook/PD/OTLP configured → the None-guarded teardown branches
    are skipped but storage is still closed (the always-on path)."""
    out = await _drive(monkeypatch, AlertingConfig())

    out["dispatcher"].run.assert_not_called()
    out["pagerduty"].run.assert_not_called()
    out["otlp"].run.assert_not_called()
    out["storage"].close.assert_awaited()
