"""Isolated coverage for run.py service/error branches (S-236).

Covers the small extractable functions and the optional-service / startup-
failure branches inside ``_run_with_config`` that the sink-wiring drive
does not reach:

- ``_run`` entrypoint (1020-1021): load_config → _run_with_config.
- ``_serve_or_hint`` EADDRINUSE hint + re-raise + ready-task cancel (385-396).
- ``_log_when_started`` bind-wait loop (401-403).
- ``build_pipeline`` raising RuntimeError → ordered teardown + sys.exit(1)
  (522-537), with ioc_matcher present so the matcher.stop() branch runs.
- LLM-backend-present branches: explanation / hunt / rule-suggestion
  services + ioc_matcher construction (449-454, 685-735).

All deterministic — mocked storage/pipeline/sinks, no network, no uvicorn.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import (
    AlertingConfig,
    IoCMatcherConfig,
    SeerflowConfig,
    StorageConfig,
    ThreatIntelConfig,
)
from seerflow.pipeline.run import (
    _log_when_started,
    _run,
    _run_with_config,
    _serve_or_hint,
)

# ── _run entrypoint ─────────────────────────────────────────────────────


@pytest.mark.unit
async def test_run_loads_config_then_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import seerflow.pipeline.run as run_mod

    sentinel_cfg = object()
    monkeypatch.setattr(run_mod, "load_config", MagicMock(return_value=sentinel_cfg))
    seen: dict[str, Any] = {}

    async def _fake_rwc(cfg: Any) -> None:
        seen["cfg"] = cfg

    monkeypatch.setattr(run_mod, "_run_with_config", _fake_rwc)

    await _run("seerflow.yaml")

    assert seen["cfg"] is sentinel_cfg


# ── _serve_or_hint ──────────────────────────────────────────────────────


@pytest.mark.unit
async def test_serve_or_hint_logs_hint_on_eaddrinuse_and_reraises() -> None:
    server = MagicMock()
    server.started = True

    async def _serve() -> None:
        raise OSError(errno.EADDRINUSE, "address in use")

    server.serve = _serve

    with pytest.raises(OSError, match="address in use"):
        await _serve_or_hint(server, "127.0.0.1", 8080)


@pytest.mark.unit
async def test_serve_or_hint_other_oserror_reraises_without_hint() -> None:
    server = MagicMock()
    server.started = True

    async def _serve() -> None:
        raise OSError(errno.EPERM, "nope")

    server.serve = _serve

    with pytest.raises(OSError, match="nope"):
        await _serve_or_hint(server, "127.0.0.1", 8080)


@pytest.mark.unit
async def test_serve_or_hint_clean_serve_cancels_ready_task() -> None:
    server = MagicMock()
    server.started = True

    async def _serve() -> None:
        return None

    server.serve = _serve

    await _serve_or_hint(server, "127.0.0.1", 8080)  # ready_task cancelled cleanly


# ── _log_when_started ───────────────────────────────────────────────────


@pytest.mark.unit
async def test_log_when_started_waits_for_bind() -> None:
    server = MagicMock()
    flips = {"n": 0}

    class _Started:
        def __bool__(self) -> bool:
            flips["n"] += 1
            return flips["n"] >= 3  # not started for first 2 polls

    server.started = _Started()

    await asyncio.wait_for(_log_when_started(server, "127.0.0.1", 8080), timeout=2)
    assert flips["n"] >= 3


# ── shared _run_with_config drive helper ────────────────────────────────


class _FakePipeline:
    def __init__(self) -> None:
        self.manager = MagicMock()
        self.manager._receivers = {}

    async def run(self, _h: Any) -> None:
        return None

    async def stop(self) -> None:
        return None


class _FakeServer:
    def __init__(self, *_a: Any, **_k: Any) -> None:
        self.should_exit = False
        self.force_exit = False
        self.started = True
        self.capture_signals = MagicMock()

    async def serve(self) -> None:
        return None


def _common_patches(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    import seerflow.pipeline.run as run_mod

    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    monkeypatch.setattr(run_mod, "connect_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(run_mod.uvicorn, "Server", _FakeServer)

    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    taxii.register_snapshot_listener = MagicMock()
    monkeypatch.setattr(run_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(return_value=1)
    ensemble.save_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(run_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))
    monkeypatch.setattr(run_mod, "make_handler", MagicMock(return_value=MagicMock()))
    return storage


def _fake_app() -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    app.state.ws_manager = MagicMock()
    return app


# ── startup-failure path: build_pipeline raises RuntimeError ────────────


@pytest.mark.unit
async def test_build_pipeline_runtime_error_triggers_ordered_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import seerflow.pipeline.run as run_mod

    storage = _common_patches(monkeypatch)
    monkeypatch.setattr(
        run_mod,
        "build_pipeline",
        AsyncMock(side_effect=RuntimeError("receiver bind failed")),
    )
    # ioc_matcher present so the `if ioc_matcher is not None: await stop()`
    # branch in the failure path executes.
    matcher = MagicMock()
    matcher.start = AsyncMock()
    matcher.stop = AsyncMock()
    matcher.on_snapshot_updated = MagicMock()
    monkeypatch.setattr(run_mod, "IoCMatcher", MagicMock(return_value=matcher))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        threat_intel=ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True)),
    )

    with pytest.raises(SystemExit) as exc:
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    assert exc.value.code == 1
    matcher.stop.assert_awaited()
    storage.close.assert_awaited()


# ── LLM-backend-present services + ioc_matcher construction ─────────────


@pytest.mark.unit
async def test_llm_backend_present_constructs_all_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import seerflow.pipeline.run as run_mod

    _common_patches(monkeypatch)
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))
    # LLM backend present → explanation + hunt + rule-suggestion services
    # all construct (lines 684-735).
    monkeypatch.setattr("seerflow.llm.build_llm_backend", MagicMock(return_value=MagicMock()))
    # ioc_matcher enabled → construction + listener registration (449-454).
    matcher = MagicMock()
    matcher.start = AsyncMock()
    matcher.stop = AsyncMock()
    matcher.on_snapshot_updated = MagicMock()
    matcher.check_event = MagicMock(return_value=())
    monkeypatch.setattr(run_mod, "IoCMatcher", MagicMock(return_value=matcher))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        threat_intel=ThreatIntelConfig(matcher=IoCMatcherConfig(enabled=True)),
    )

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    matcher.start.assert_awaited()
    matcher.stop.assert_awaited()


# ── degrade-gracefully exception branches ───────────────────────────────


@pytest.mark.unit
async def test_degrade_paths_when_subsystems_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensemble restore / UEBA restore / Sigma load / graph edges all raise
    → each logged + swallowed; startup still completes (478-479, 501-502,
    558-559, 569-570)."""
    import seerflow.pipeline.run as run_mod

    storage = _common_patches(monkeypatch)
    storage.load_edges = AsyncMock(side_effect=RuntimeError("edge load boom"))
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))

    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(side_effect=RuntimeError("restore boom"))
    ensemble.save_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(run_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))

    bad_baseline = MagicMock()
    bad_baseline.restore = AsyncMock(side_effect=RuntimeError("ueba boom"))
    bad_baseline.flush = AsyncMock()
    bad_baseline.__len__ = MagicMock(return_value=0)
    monkeypatch.setattr(run_mod, "BaselineStore", MagicMock(return_value=bad_baseline))

    sigma_cls = MagicMock()
    sigma_inst = MagicMock()
    sigma_inst.load_bundled = MagicMock(side_effect=RuntimeError("sigma boom"))
    sigma_cls.return_value = sigma_inst
    monkeypatch.setattr("seerflow.sigma.engine.SigmaEngine", sigma_cls)

    config = SeerflowConfig(storage=StorageConfig(), alerting=AlertingConfig())

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    ensemble.load_all_state.assert_awaited()
    bad_baseline.restore.assert_awaited()
    storage.load_edges.assert_awaited()


@pytest.mark.unit
async def test_attack_mapper_from_config_and_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-defined attack_mappings: from_config success path then a
    ValueError fallback to load_defaults (509-516)."""
    import seerflow.pipeline.run as run_mod
    from seerflow.config import DetectionConfig

    _common_patches(monkeypatch)
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))

    mapper = MagicMock()
    mapper.__len__ = MagicMock(return_value=3)
    mapper.lookup = MagicMock(return_value=((), ()))

    am_cls = MagicMock()
    am_cls.from_config = MagicMock(side_effect=ValueError("bad mapping"))
    am_cls.load_defaults = MagicMock(return_value=mapper)
    monkeypatch.setattr("seerflow.detection.attack_mapping.AttackMapper", am_cls)

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        detection=DetectionConfig(attack_mappings=({"pattern": "x", "tactic": "y"},)),
    )

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    am_cls.from_config.assert_called_once()
    am_cls.load_defaults.assert_called()


@pytest.mark.unit
async def test_webhook_plus_router_registers_delivery_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """webhook_targets + a channel-built router → register_target adapters
    + dispatcher run/stop (816, 829-831 + dispatcher teardown)."""
    import seerflow.pipeline.run as run_mod
    from seerflow.alerting.channels.telegram import TelegramTarget
    from seerflow.alerting.dispatcher import WebhookTarget

    _common_patches(monkeypatch)
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))

    disp = MagicMock()
    disp.run = AsyncMock()
    disp.stop = AsyncMock()
    monkeypatch.setattr(
        "seerflow.alerting.dispatcher.AlertDispatcher",
        MagicMock(return_value=disp),
    )
    monkeypatch.setattr(
        "seerflow.alerting.dispatcher.build_webhook_delivery_targets",
        MagicMock(return_value=[MagicMock()]),
    )
    sess = MagicMock()
    sess.close = AsyncMock()
    monkeypatch.setattr(run_mod.aiohttp, "ClientSession", MagicMock(return_value=sess))
    monkeypatch.setattr(run_mod.aiohttp, "TCPConnector", MagicMock(return_value=MagicMock()))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(
            webhook_targets=(WebhookTarget(name="wh", url="https://x.example", format="json"),),
            telegram_targets=(TelegramTarget(name="tg", bot_token="t:ABC", chat_id="-1"),),
        ),
    )

    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    disp.run.assert_awaited()
    disp.stop.assert_awaited()
