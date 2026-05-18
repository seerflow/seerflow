"""Characterization test for ``seerflow.pipeline.run._run_with_config`` (S-301).

Pins the exact engine/holder/scalar wiring fed into ``make_handler`` so the
S-302 ``assemble_handler`` factory extraction and the S-304 live-caller
refactor are provably behaviour-preserving — any wiring drift fails here
before it reaches the shipped live pipeline.

This is a *characterization* test (Feathers): it documents what
``_run_with_config`` does *today*, not what it *should* do. An intentional
wiring change is expected to fail this test and must be updated in the same
PR as the change — wiring changes become visible and reviewed, never silent.

Self-contained: the stub stack mirrors ``test_pipeline_run_sinks._drive``
but is NOT cross-imported — a regression guard must not depend on another
test module's private helper. Everything is mocked: no real uvicorn, no
network, no storage I/O. The ``make_handler`` call is unconditional at
``run.py:876`` so the capturing spy is reliably populated even with no
optional sinks configured.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import AlertingConfig, SeerflowConfig, StorageConfig
from seerflow.pipeline.run import _run_with_config


class _FakePipeline:
    """Pipeline stub: run() returns at once, stop() is a noop."""

    def __init__(self) -> None:
        self.manager = MagicMock()
        self.manager._receivers = {}

    async def run(self, _handler: Any) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeServer:
    """uvicorn.Server stand-in — serve() returns at once."""

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


def _stub_storage() -> MagicMock:
    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    storage.load_iocs = AsyncMock(return_value=[])
    storage.get_model_state = AsyncMock(return_value=None)
    storage.load_baselines = AsyncMock(return_value=[])
    return storage


async def _drive_and_capture(
    monkeypatch: pytest.MonkeyPatch, config: SeerflowConfig
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Run ``_run_with_config`` to completion with everything stubbed.

    Returns ``(make_handler_spy, ensemble_stub, storage_stub)`` so callers
    can pin positional args by identity and assert on the captured call.
    """
    import seerflow.pipeline.run as run_mod

    storage = _stub_storage()
    monkeypatch.setattr(run_mod, "connect_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))
    # String-target form: ``run.py`` does ``import uvicorn`` so this patches
    # the same module object, and avoids the mypy --strict implicit-reexport
    # ``attr-defined`` smell that ``run_mod.uvicorn`` triggers.
    monkeypatch.setattr("uvicorn.Server", _FakeServer)

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

    # The real handler is a bare ``async def handler(event)`` closure with no
    # ``get_stats`` attribute, so the teardown ``_persist_session_state``
    # path (run.py:175) skips its flush branch. Return a faithful async
    # callable rather than an AsyncMock so that ``getattr(handler,
    # "get_stats", None)`` resolves to None (an AsyncMock would auto-create
    # a child that returns an un-awaited coroutine and emit a RuntimeWarning).
    async def _handler_stub(_event: Any) -> None:  # pragma: no cover - never invoked
        return None

    spy = MagicMock(return_value=_handler_stub)
    monkeypatch.setattr(run_mod, "make_handler", spy)

    sess = MagicMock()
    sess.close = AsyncMock()
    # ``run.py`` does ``import aiohttp`` so the string-target form patches the
    # same module object ``run_mod.aiohttp`` references; monkeypatch reverts
    # it automatically. Preferred over ``run_mod.aiohttp`` attribute access,
    # which mypy --strict flags as an implicit re-export (``attr-defined``).
    monkeypatch.setattr("aiohttp.ClientSession", MagicMock(return_value=sess))
    monkeypatch.setattr("aiohttp.TCPConnector", MagicMock(return_value=MagicMock()))

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    return spy, ensemble, storage


@pytest.mark.unit
async def test_default_config_wiring_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SeerflowConfig() defaults: pin every engine/holder + scalar fed into
    make_handler, plus the default-flag-gated slots (UEBA + kill-chain ON,
    IoC matcher OFF — empirically verified defaults)."""
    from seerflow.api.latency import StageLatencyTracker
    from seerflow.correlation.graph_structural import GraphStructuralEvaluator
    from seerflow.correlation.holders import EngineHolder
    from seerflow.correlation.risk import RiskRegister
    from seerflow.correlation.watermark import Watermark
    from seerflow.correlation.window import EntityWindowBuffer
    from seerflow.detection.attack_mapping import AttackMapper
    from seerflow.graph.entity_graph import EntityGraph
    from seerflow.ueba.engine import UEBAEngine
    from seerflow.ueba.store import BaselineStore

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    spy, ensemble, storage = await _drive_and_capture(monkeypatch, config)

    assert spy.call_count == 1
    args, kw = spy.call_args.args, spy.call_args.kwargs

    # Positional args: the stubbed DetectionEnsemble instance, then storage.
    assert len(args) == 2
    assert args[0] is ensemble
    assert args[1] is storage

    # Engine/holder types built from real (un-stubbed) classes.
    assert isinstance(kw["sigma_holder"], EngineHolder)
    assert isinstance(kw["correlation_holder"], EngineHolder)
    assert isinstance(kw["entity_graph"], EntityGraph)
    assert isinstance(kw["window_buffer"], EntityWindowBuffer)
    assert isinstance(kw["watermark"], Watermark)
    assert isinstance(kw["risk_register"], RiskRegister)
    assert isinstance(kw["attack_mapper"], AttackMapper)
    assert isinstance(kw["graph_structural"], GraphStructuralEvaluator)
    assert isinstance(kw["latency_tracker"], StageLatencyTracker)
    # ws_manager is the shared instance read off api_app.state.ws_manager.
    assert kw["ws_manager"] is not None

    # Default-flag-gated slots (SeerflowConfig() defaults, empirically
    # verified: ueba.enabled=True, kill_chain.enabled=True,
    # threat_intel.matcher.enabled=False).
    assert isinstance(kw["baseline_store"], BaselineStore)
    assert isinstance(kw["ueba_engine"], UEBAEngine)
    assert kw["kill_chain_tracker"] is not None
    assert kw["ioc_matcher"] is None
    assert kw["alert_dispatcher"] is None

    # Key scalars derived from the live config object (not hard-coded), so
    # the pin survives a future default change while still catching drift.
    assert kw["save_interval_ns"] == config.detection.model_save_interval_seconds * 1_000_000_000
    assert kw["graph_algo_interval"] == config.detection.graph_algo_interval
    assert kw["ueba_alert_cooldown_ns"] == config.ueba.alert_cooldown_seconds * 1_000_000_000
    assert kw["alerting_config"] is config.alerting


@pytest.mark.unit
async def test_inverted_flags_wiring_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UEBA off + kill-chain off + IoC matcher on → pin the *opposite*
    branch of every flag-gated make_handler slot.

    Together with ``test_default_config_wiring_is_pinned`` this exercises
    BOTH branches of every flag gate, so the regression guard catches a
    refactor that inverts or drops a gate.

    The four flag-gated classes are sentinel-stubbed so the *enabled* path
    (IoCMatcher) is deterministic and side-effect-free (``IoCMatcher.start``
    / ``BaselineStore.restore`` would otherwise touch storage + register a
    snapshot listener). The default-config test deliberately does NOT stub
    them — so the two scenarios pin the real engines on one branch and the
    None gate on the other.
    """
    import seerflow.pipeline.run as run_mod
    from seerflow.config import (
        DetectionConfig,
        IoCMatcherConfig,
        KillChainConfig,
        ThreatIntelConfig,
        UEBAConfig,
    )

    ioc_sentinel = MagicMock(name="IoCMatcher")
    ioc_sentinel.start = AsyncMock()
    ioc_sentinel.stop = AsyncMock()
    ioc_sentinel.on_snapshot_updated = MagicMock()
    monkeypatch.setattr(run_mod, "IoCMatcher", MagicMock(return_value=ioc_sentinel))

    # Immutable construction (no in-place mutation): flip the three flag
    # gates away from their defaults via explicit nested configs.
    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        ueba=UEBAConfig(enabled=False),
        detection=DetectionConfig(kill_chain=KillChainConfig(enabled=False)),
        threat_intel=ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True)),
        shutdown_timeout_s=1.0,
    )
    spy, _ensemble, _storage = await _drive_and_capture(monkeypatch, config)

    assert spy.call_count == 1
    kw = spy.call_args.kwargs

    # UEBA + kill-chain disabled → those slots are None (opposite of the
    # default-config scenario, which pins the real engines).
    assert kw["baseline_store"] is None
    assert kw["ueba_engine"] is None
    assert kw["kill_chain_tracker"] is None
    # Matcher enabled → the IoCMatcher sentinel is wired through.
    assert kw["ioc_matcher"] is ioc_sentinel
