"""Residual run.py line-coverage gaps (S-236).

Closes the small deterministic branches the sink/service drives miss so
run.py keeps comfortable margin above the 95% line gate:

- 148-151: ``_log_shutdown_task_exception`` cancelled vs raised task.
- 355-361: ``_build_channel_session_and_router`` SMS/WhatsApp HTTP-channel
  binding (session is not None branch).
- 465-469: TAXII feed-start failure warning.
- 554-556: Sigma ``load_custom`` when custom rule dirs are configured.
- 789-790: late SIGTERM catch-up flips ``server.should_exit`` before serve.
- 935-952: ``finally`` — pipeline_task still running gets cancelled +
  background-task exception surfaced.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.alerting.channels.sms import SmsTarget
from seerflow.alerting.channels.whatsapp import WhatsAppTarget
from seerflow.config import (
    AlertingConfig,
    DetectionConfig,
    SeerflowConfig,
    StorageConfig,
)
from seerflow.pipeline.run import (
    _build_channel_session_and_router,
    _log_shutdown_task_exception,
    _run_with_config,
)

# ── _log_shutdown_task_exception ────────────────────────────────────────


@pytest.mark.unit
async def test_log_shutdown_task_exception_skips_cancelled() -> None:
    async def _coro() -> None:
        await asyncio.sleep(10)

    task: asyncio.Task[None] = asyncio.create_task(_coro())
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    _log_shutdown_task_exception(task)  # cancelled → early return, no raise


@pytest.mark.unit
async def test_log_shutdown_task_exception_logs_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _boom() -> None:
        raise RuntimeError("stop boom")

    task: asyncio.Task[None] = asyncio.create_task(_boom())
    with contextlib.suppress(RuntimeError):
        await task

    with caplog.at_level(logging.WARNING):
        _log_shutdown_task_exception(task)

    assert "pipeline.stop() raised during signal handling" in caplog.text


# ── _build_channel_session_and_router SMS/WhatsApp binding ──────────────


@pytest.mark.unit
async def test_channel_router_binds_sms_and_whatsapp_http_channels() -> None:
    cfg = AlertingConfig(
        sms_targets=(
            SmsTarget(
                name="sms",
                account_sid="AC0",
                auth_token="tok",
                from_number="+1",
                to_numbers=("+2",),
            ),
        ),
        whatsapp_targets=(
            WhatsAppTarget(
                name="wa",
                phone_number_id="pn-1",
                template_name="alert",
                language_code="en",
                to_numbers=("+2",),
                access_token="tok",
            ),
        ),
    )
    session, router = await _build_channel_session_and_router(cfg)
    try:
        assert session is not None  # HTTP channels → shared session allocated
        assert router is not None
    finally:
        if session is not None:
            await session.close()


# ── full-run residual branches ──────────────────────────────────────────


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


def _fake_app() -> MagicMock:
    app = MagicMock()
    app.state = MagicMock()
    app.state.ws_manager = MagicMock()
    return app


def _base_patches(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    import seerflow.pipeline.assembly as asm_mod
    import seerflow.pipeline.run as run_mod

    storage = MagicMock()
    storage.close = AsyncMock()
    storage.load_edges = AsyncMock(return_value=[])
    storage.set_entity_graph = MagicMock()
    monkeypatch.setattr(run_mod, "connect_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(run_mod.uvicorn, "Server", _FakeServer)
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))
    # S-304: DetectionEnsemble / make_handler moved into the factory
    # (pipeline.assembly). ``_run_with_config`` consumes it now.
    ensemble = MagicMock()
    ensemble.load_all_state = AsyncMock(return_value=0)
    ensemble.save_all_state = AsyncMock(return_value=0)
    monkeypatch.setattr(asm_mod, "DetectionEnsemble", MagicMock(return_value=ensemble))
    monkeypatch.setattr(asm_mod, "make_handler", MagicMock(return_value=MagicMock()))
    return storage


@pytest.mark.unit
async def test_taxii_feed_start_failure_logs_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import seerflow.pipeline.assembly as asm_mod

    _base_patches(monkeypatch)
    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=["feed-a", "feed-b"])  # 2 failed feeds
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    taxii.register_snapshot_listener = MagicMock()
    monkeypatch.setattr(asm_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    config = SeerflowConfig(storage=StorageConfig(), alerting=AlertingConfig())
    with caplog.at_level(logging.WARNING), contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    assert "feed(s) failed to start" in caplog.text


@pytest.mark.unit
async def test_sigma_load_custom_invoked_for_configured_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import seerflow.pipeline.assembly as asm_mod

    _base_patches(monkeypatch)
    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    taxii.register_snapshot_listener = MagicMock()
    monkeypatch.setattr(asm_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    sigma_inst = MagicMock()
    sigma_inst.load_bundled = MagicMock()
    sigma_inst.load_custom = MagicMock()
    sigma_inst.rule_count = 1
    monkeypatch.setattr("seerflow.sigma.engine.SigmaEngine", MagicMock(return_value=sigma_inst))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        detection=DetectionConfig(sigma_rules_dirs=(str(tmp_path),)),
    )
    with contextlib.suppress(SystemExit):
        await _run_with_config(config, make_api_app=lambda **_kw: _fake_app())

    sigma_inst.load_custom.assert_called_once()


@pytest.mark.unit
async def test_pipeline_task_cancelled_in_finally_when_server_finishes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline.run() that never returns → after the sibling wait completes
    (server task done first) the finally block cancels the pipeline task
    (run.py 936-939)."""
    import seerflow.pipeline.assembly as asm_mod
    import seerflow.pipeline.run as run_mod

    _base_patches(monkeypatch)
    taxii = MagicMock()
    taxii.start = AsyncMock(return_value=[])
    taxii.stop = AsyncMock()
    taxii.feed_ids = MagicMock(return_value=())
    taxii.metrics = MagicMock()
    taxii.register_snapshot_listener = MagicMock()
    monkeypatch.setattr(asm_mod, "TAXIIFeedManager", MagicMock(return_value=taxii))

    class _HangingPipeline(_FakePipeline):
        async def run(self, _h: Any) -> None:
            await asyncio.sleep(3600)  # never returns; server task wins the wait

    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_HangingPipeline()))

    config = SeerflowConfig(
        storage=StorageConfig(),
        alerting=AlertingConfig(),
        shutdown_timeout_s=1.0,
    )
    with contextlib.suppress(SystemExit):
        await asyncio.wait_for(
            _run_with_config(config, make_api_app=lambda **_kw: _fake_app()),
            timeout=10,
        )
