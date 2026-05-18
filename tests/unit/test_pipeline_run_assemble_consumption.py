"""S-304: ``_run_with_config`` consumes ``assemble_handler`` (live-integration).

Pins that the live runner builds its detection handler via the shared
factory (S-302 seam) and supplies the real ``ConnectionManager`` read off
``api_app.state.ws_manager`` (the one intentional divergence from the
factory default of ``None``), and that the startup-failure path tears down
the assembled resources before closing storage.

Self-contained stub stack: a regression guard must not cross-import another
test module's private helpers. Everything mocked: no real uvicorn, no
network, no storage I/O.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from seerflow.config import AlertingConfig, SeerflowConfig, StorageConfig


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
    app.state.ws_manager = MagicMock(name="real_ws_manager")
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


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    import seerflow.pipeline.run as run_mod

    storage = _stub_storage()
    monkeypatch.setattr(run_mod, "connect_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr("uvicorn.Server", _FakeServer)
    return storage


@pytest.mark.unit
async def test_run_with_config_calls_assemble_handler_with_real_ws_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_with_config drives the shared factory and forwards the real
    ConnectionManager (not None) so the pipeline + WS route share fan-out."""
    import seerflow.pipeline.run as run_mod

    storage = _patch_common(monkeypatch)
    monkeypatch.setattr(run_mod, "build_pipeline", AsyncMock(return_value=_FakePipeline()))

    async def _handler(_e: Any) -> None:  # pragma: no cover - never invoked
        return None

    captured: dict[str, Any] = {}
    teardown = AsyncMock()

    async def _fake_assemble(cfg: Any, stg: Any, **kw: Any) -> Any:
        captured["ws_manager"] = kw.get("ws_manager")
        captured["storage"] = stg
        captured["config"] = cfg
        return MagicMock(
            handler=_handler, lifecycle=(), teardown=teardown, capture_sink=None
        )

    monkeypatch.setattr(run_mod, "assemble_handler", _fake_assemble)

    cfg = SeerflowConfig(
        storage=StorageConfig(), alerting=AlertingConfig(), shutdown_timeout_s=1.0
    )
    with contextlib.suppress(SystemExit):
        await run_mod._run_with_config(cfg, make_api_app=lambda **_k: _fake_app())

    assert captured["storage"] is storage
    assert captured["config"] is cfg
    # The one intentional divergence from the factory default (None): the
    # live caller injects the real ConnectionManager from api_app.state.
    assert captured["ws_manager"] is not None
    teardown.assert_awaited()


@pytest.mark.unit
async def test_startup_failure_tears_down_assembled_then_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_pipeline RuntimeError → assembled.teardown() then storage.close()
    then SystemExit(1). No background task is stranded on the failure path."""
    import seerflow.pipeline.run as run_mod

    storage = _patch_common(monkeypatch)
    monkeypatch.setattr(
        run_mod, "build_pipeline", AsyncMock(side_effect=RuntimeError("boom"))
    )

    order: list[str] = []
    teardown = AsyncMock(side_effect=lambda: order.append("teardown"))
    storage.close = AsyncMock(side_effect=lambda: order.append("storage_close"))

    async def _fake_assemble(cfg: Any, stg: Any, **kw: Any) -> Any:
        return MagicMock(
            handler=AsyncMock(), lifecycle=(), teardown=teardown, capture_sink=None
        )

    monkeypatch.setattr(run_mod, "assemble_handler", _fake_assemble)

    cfg = SeerflowConfig(
        storage=StorageConfig(), alerting=AlertingConfig(), shutdown_timeout_s=1.0
    )
    with pytest.raises(SystemExit) as exc_info:
        await run_mod._run_with_config(cfg, make_api_app=lambda **_k: _fake_app())

    assert exc_info.value.code == 1
    teardown.assert_awaited_once()
    storage.close.assert_awaited()
    # teardown must run before storage.close (assembled resources first,
    # storage last for SQLite WAL safety).
    assert order == ["teardown", "storage_close"]
