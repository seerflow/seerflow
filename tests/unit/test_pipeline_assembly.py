"""Unit tests for ``seerflow.pipeline.assembly.assemble_handler`` (S-302).

Mirrors the S-301 characterization assertions
(``tests/unit/test_pipeline_run_characterization.py``) so the extracted
factory is provably the same wiring ``_run_with_config`` feeds into
``make_handler`` — except ``ws_manager`` is ``None`` by design (the factory
builds no FastAPI app; S-304 re-supplies the live instance).

Self-contained stub stack: a regression guard must not cross-import another
test module's private helpers. Everything mocked: no real network, no
storage I/O.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import AlertingConfig, SeerflowConfig, StorageConfig
from seerflow.pipeline.assembly import AssembledHandler, assemble_handler


def _stub_storage() -> MagicMock:
    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    storage.load_iocs = AsyncMock(return_value=[])
    storage.get_model_state = AsyncMock(return_value=None)
    storage.load_baselines = AsyncMock(return_value=[])
    return storage


@pytest.mark.unit
async def test_assembled_handler_shape() -> None:
    """assemble_handler returns an AssembledHandler with handler/lifecycle/teardown."""
    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    storage = _stub_storage()

    result = await assemble_handler(config, storage)

    assert isinstance(result, AssembledHandler)
    assert callable(result.handler)
    assert isinstance(result.lifecycle, tuple)
    assert callable(result.teardown)
    await result.teardown()


async def _assemble_and_capture(
    monkeypatch: pytest.MonkeyPatch, config: SeerflowConfig
) -> tuple[MagicMock, MagicMock, MagicMock, AssembledHandler]:
    """Drive assemble_handler with a capturing make_handler spy.

    Returns (make_handler_spy, ensemble_stub, storage_stub, result).
    """
    import seerflow.pipeline.assembly as asm_mod

    storage = _stub_storage()

    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    taxii.register_snapshot_listener = MagicMock()
    monkeypatch.setattr(asm_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(return_value=0)
    ensemble.save_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(asm_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))

    async def _handler_stub(_event: Any) -> None:  # pragma: no cover - never invoked
        return None

    spy = MagicMock(return_value=_handler_stub)
    monkeypatch.setattr(asm_mod, "make_handler", spy)

    result = await assemble_handler(config, storage)
    return spy, ensemble, storage, result


@pytest.mark.unit
async def test_default_config_wiring_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SeerflowConfig() defaults: pin every engine/holder + scalar fed into
    make_handler. Mirrors S-301 test_default_config_wiring_is_pinned EXCEPT
    ws_manager is None (factory builds no FastAPI app — by design)."""
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
    spy, ensemble, storage, result = await _assemble_and_capture(monkeypatch, config)

    assert spy.call_count == 1
    args, kw = spy.call_args.args, spy.call_args.kwargs

    assert len(args) == 2
    assert args[0] is ensemble
    assert args[1] is storage

    assert isinstance(kw["sigma_holder"], EngineHolder)
    assert isinstance(kw["correlation_holder"], EngineHolder)
    assert isinstance(kw["entity_graph"], EntityGraph)
    assert isinstance(kw["window_buffer"], EntityWindowBuffer)
    assert isinstance(kw["watermark"], Watermark)
    assert isinstance(kw["risk_register"], RiskRegister)
    assert isinstance(kw["attack_mapper"], AttackMapper)
    assert isinstance(kw["graph_structural"], GraphStructuralEvaluator)
    assert isinstance(kw["latency_tracker"], StageLatencyTracker)
    # Deliberate divergence from S-301: no FastAPI app in the factory.
    assert kw["ws_manager"] is None

    assert isinstance(kw["baseline_store"], BaselineStore)
    assert isinstance(kw["ueba_engine"], UEBAEngine)
    assert kw["kill_chain_tracker"] is not None
    assert kw["ioc_matcher"] is None
    assert kw["alert_dispatcher"] is None

    assert kw["save_interval_ns"] == config.detection.model_save_interval_seconds * 1_000_000_000
    assert kw["graph_algo_interval"] == config.detection.graph_algo_interval
    assert kw["ueba_alert_cooldown_ns"] == config.ueba.alert_cooldown_seconds * 1_000_000_000
    assert kw["alerting_config"] is config.alerting

    await result.teardown()


@pytest.mark.unit
async def test_inverted_flags_wiring_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UEBA off + kill-chain off + IoC matcher on → pin the opposite branch
    of every flag-gated make_handler slot. Mirrors S-301
    test_inverted_flags_wiring_is_pinned."""
    import seerflow.pipeline.assembly as asm_mod
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
    monkeypatch.setattr(asm_mod, "IoCMatcher", MagicMock(return_value=ioc_sentinel))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        ueba=UEBAConfig(enabled=False),
        detection=DetectionConfig(kill_chain=KillChainConfig(enabled=False)),
        threat_intel=ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True)),
        shutdown_timeout_s=1.0,
    )
    spy, _ensemble, _storage, result = await _assemble_and_capture(monkeypatch, config)

    assert spy.call_count == 1
    kw = spy.call_args.kwargs

    assert kw["baseline_store"] is None
    assert kw["ueba_engine"] is None
    assert kw["kill_chain_tracker"] is None
    assert kw["ioc_matcher"] is ioc_sentinel

    await result.teardown()


@pytest.mark.unit
async def test_teardown_is_idempotent_and_does_not_close_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """teardown() twice is safe; it stops TAXII and cancels the rule
    reloader but never closes caller-owned storage."""
    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    spy, _ensemble, storage, result = await _assemble_and_capture(monkeypatch, config)

    # rule reloader task is always present in lifecycle
    assert len(result.lifecycle) == 1
    reload_task = result.lifecycle[0]

    await result.teardown()
    await result.teardown()  # second call is a no-op (idempotent)

    assert reload_task.cancelled() or reload_task.done()
    storage.close.assert_not_called()


@pytest.mark.unit
async def test_capture_sink_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """capture_sink is surfaced on the result for the S-303 wiring seam."""
    sentinel = object()
    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    import seerflow.pipeline.assembly as asm_mod

    storage = _stub_storage()
    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    monkeypatch.setattr(asm_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))
    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(asm_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))

    async def _h(_e: Any) -> None:  # pragma: no cover
        return None

    monkeypatch.setattr(asm_mod, "make_handler", MagicMock(return_value=_h))

    result = await assemble_handler(config, storage, capture_sink=sentinel)
    assert result.capture_sink is sentinel
    await result.teardown()
